"""
Permission-aware SQL predicate builder.

Translates a principal's MappingProvider resolution into composable
SQL WHERE predicate sets.  Dual-mode: to_sql() for asyncpg, filter()
for in-memory evaluation.

Foreseen feature — designed for use with PostgresMemoryStore but
intentionally decoupled from it.

Design notes
------------
- All user-supplied values are carried as *params*, never interpolated
  into the SQL string.  This prevents SQL injection by construction.
- Placeholder numbering uses asyncpg's positional ``$N`` syntax.
- The ``filter()`` method evaluates the same logical predicates in Python
  so that InMemoryStore and PostgresMemoryStore share identical permission
  semantics.

Supported predicate types
--------------------------
* ``scope = ANY($N)``                 — scope allow-list
* ``scope_path LIKE $N``             — path-prefix restriction
* ``value_json->>'field' != ALL($N::text[])`` — exclusion list
* ``value_json->>'field' = $N``      — equality

Unknown SQL templates pass through (conservative: item is included).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from cemaf.core.enums import MemoryScope
from cemaf.memory.base import MemoryItem
from cemaf.security.mappings import MappingProvider

# ---------------------------------------------------------------------------
# Predicate + PredicateSet value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Predicate:
    """
    A single SQL condition with positional parameters.

    ``sql`` must use ``$N`` placeholders (asyncpg syntax).  ``params`` holds
    the corresponding values in order.  ``description`` is for human readers.

    Example::

        Predicate(
            sql="scope = ANY($1)",
            params=(["project", "session"],),
            description="allowed scopes",
        )
    """

    sql: str
    params: tuple[Any, ...]
    description: str = ""


@dataclass(frozen=True)
class PredicateSet:
    """
    An immutable collection of Predicates that are ANDed together.

    The ``$N`` placeholder numbers in each individual Predicate are local
    (always start at 1).  ``to_sql()`` renumbers them to form a globally
    consistent sequence.
    """

    predicates: tuple[Predicate, ...] = field(default_factory=tuple)

    def append(self, predicate: Predicate) -> PredicateSet:
        """Return a new PredicateSet with *predicate* appended (immutable)."""
        return PredicateSet(predicates=(*self.predicates, predicate))

    def to_sql(self, offset: int = 1) -> str:
        """
        Join all predicate SQL fragments with `` AND ``, renumbering ``$N``
        placeholders starting from *offset*.

        Returns an empty string if there are no predicates.
        """
        if not self.predicates:
            return ""

        parts: list[str] = []
        counter = offset

        for pred in self.predicates:
            sql = pred.sql
            # Count how many $N appear in this predicate's sql
            local_placeholders = sorted(
                {int(m) for m in re.findall(r"\$(\d+)", sql)},
                reverse=True,  # replace largest first to avoid e.g. $1 hitting $10
            )
            for local_n in local_placeholders:
                global_n = counter + local_n - 1
                # Replace '$N' occurrences (not followed by another digit)
                sql = re.sub(
                    rf"\${local_n}(?!\d)",
                    f"${global_n}",
                    sql,
                )
            parts.append(sql)
            # Advance counter by the number of distinct placeholders in this pred
            n_placeholders = len(set(re.findall(r"\$(\d+)", pred.sql)))
            counter += n_placeholders

        return " AND ".join(parts)

    def to_params(self) -> tuple[Any, ...]:
        """Return a flat tuple of all parameter values in predicate order."""
        result: list[Any] = []
        for pred in self.predicates:
            result.extend(pred.params)
        return tuple(result)

    def filter(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """
        Evaluate all predicates in Python and return the subset of *items*
        that satisfy every predicate (AND semantics).

        Supported SQL templates (matched by pattern):

        * ``scope = ANY($1)``
        * ``scope_path LIKE $1``
        * ``value_json->>'<field>' != ALL($1::text[])``
        * ``value_json->>'<field>' = $1``

        Unknown templates are ignored (conservative — item is included).
        """
        result: list[MemoryItem] = []
        for item in items:
            if self._item_passes(item):
                result.append(item)
        return result

    def _item_passes(self, item: MemoryItem) -> bool:
        """Return True if *item* satisfies every predicate."""
        param_iter_start = 0
        for pred in self.predicates:
            n_params = len(pred.params)
            pred_params = pred.params
            if not _eval_predicate(pred.sql, pred_params, item):
                return False
            param_iter_start += n_params
        return True


# ---------------------------------------------------------------------------
# Python-side predicate evaluator
# ---------------------------------------------------------------------------

_RE_SCOPE_ANY = re.compile(r"^scope\s*=\s*ANY\(\$\d+\)$", re.IGNORECASE)
_RE_SCOPE_PATH_LIKE = re.compile(r"^scope_path\s+LIKE\s+\$\d+$", re.IGNORECASE)
_RE_VALUE_NEQ_ALL = re.compile(r"^value_json->>'(\w+)'\s*!=\s*ALL\(\$\d+::text\[\]\)$", re.IGNORECASE)
_RE_VALUE_EQ = re.compile(r"^value_json->>'(\w+)'\s*=\s*\$\d+$", re.IGNORECASE)


def _eval_predicate(sql: str, params: tuple[Any, ...], item: MemoryItem) -> bool:
    """
    Evaluate a single SQL predicate against *item* in Python.

    Returns True if the item passes (should be included).
    Conservative: unknown predicate templates return True.
    """
    sql_stripped = sql.strip()

    # scope = ANY($1)  — params[0] is a list/tuple of scope value strings
    if _RE_SCOPE_ANY.match(sql_stripped):
        allowed: Any = params[0]
        return item.scope.value in allowed

    # scope_path LIKE $1  — params[0] is a LIKE pattern, e.g. '/intel/%'
    if _RE_SCOPE_PATH_LIKE.match(sql_stripped):
        pattern: str = params[0]
        if item.scope_path is None:
            return False
        prefix = pattern.rstrip("%")
        return item.scope_path.startswith(prefix)

    # value_json->>'field' != ALL($1::text[])
    m = _RE_VALUE_NEQ_ALL.match(sql_stripped)
    if m:
        field_name = m.group(1)
        excluded: Any = params[0]
        actual = str(item.value.get(field_name, ""))
        return actual not in excluded

    # value_json->>'field' = $1
    m2 = _RE_VALUE_EQ.match(sql_stripped)
    if m2:
        field_name = m2.group(1)
        expected: Any = params[0]
        actual_val = str(item.value.get(field_name, ""))
        return actual_val == str(expected)

    # Unknown template — conservative pass
    return True


# ---------------------------------------------------------------------------
# QueryEngine
# ---------------------------------------------------------------------------


class QueryEngine:
    """
    Translates a principal's access grants into a composable PredicateSet.

    Usage::

        engine = QueryEngine(mapping_provider)
        pset = engine.build_predicates("alice", base_scope=MemoryScope.PROJECT)
        sql_where = pset.to_sql()        # for asyncpg
        filtered = pset.filter(items)   # for InMemoryStore
    """

    def __init__(self, mapping_provider: MappingProvider) -> None:
        self._provider = mapping_provider

    def build_predicates(
        self,
        principal_id: str,
        *,
        base_scope: MemoryScope | None = None,
        intent: Literal["read", "write", "delete"] = "read",
        extra_filters: dict[str, Any] | None = None,
    ) -> PredicateSet:
        """
        Build a PredicateSet capturing the principal's access permissions.

        Steps:

        1. Determine which scopes are allowed for *intent* via roles +
           direct_access.
        2. Build scope allow-list predicate.
        3. Build scope_path prefix predicates from direct_access.
        4. Build ABAC exclusion predicates (``{"field": {"$exclude": [...]}}``)
        5. Build ABAC equality predicates (``{"field": scalar_value}``).
        6. Merge *extra_filters* as additional equality predicates.

        Args:
            principal_id:   Identity to evaluate.
            base_scope:     If set, restrict allowed scopes to this one
                            (intersection with the principal's granted scopes).
            intent:         The operation being attempted.
            extra_filters:  Additional ``{field: value}`` equality filters
                            applied on top of ABAC conditions.
        """
        from cemaf.security.rbac import _ROLE_PERMISSIONS, ROLE_SYSTEM  # noqa: PLC0415

        roles = self._provider.get_roles(principal_id)
        direct_accesses = self._provider.get_direct_access(principal_id)
        self._provider.get_principal(principal_id)

        pset = PredicateSet()

        # ------------------------------------------------------------------
        # 1 + 2. Scope allow-list
        # ------------------------------------------------------------------
        if ROLE_SYSTEM in roles:
            # SYSTEM sees everything — no scope restriction
            allowed_scopes: list[str] = [s.value for s in MemoryScope]
        else:
            # Collect scopes the principal may access for this intent
            granted_scopes: set[str] = set()

            # Role-level: if the role has the action, any scope is allowed
            has_global_role_perm = any(intent in _ROLE_PERMISSIONS.get(role, frozenset()) for role in roles)
            if has_global_role_perm:
                granted_scopes.update(s.value for s in MemoryScope)

            # Direct-access grants
            for grant in direct_accesses:
                if intent not in grant.actions:
                    continue
                if grant.scope is None:
                    granted_scopes.update(s.value for s in MemoryScope)
                else:
                    granted_scopes.add(grant.scope.value)

            if base_scope is not None:
                # Intersect: only allow base_scope if it's in the granted set
                if base_scope.value in granted_scopes:
                    allowed_scopes = [base_scope.value]
                else:
                    allowed_scopes = []
            else:
                allowed_scopes = list(granted_scopes)

        if allowed_scopes:
            pset = pset.append(
                Predicate(
                    sql="scope = ANY($1)",
                    params=(allowed_scopes,),
                    description=f"allowed scopes for {principal_id}",
                )
            )

        # ------------------------------------------------------------------
        # 3. Scope-path prefix predicates
        # ------------------------------------------------------------------
        path_prefixes: list[str] = []
        for grant in direct_accesses:
            if grant.scope_path_prefix is not None and intent in grant.actions:
                path_prefixes.append(grant.scope_path_prefix)

        for prefix in path_prefixes:
            like_pattern = prefix if prefix.endswith("%") else prefix + "%"
            pset = pset.append(
                Predicate(
                    sql="scope_path LIKE $1",
                    params=(like_pattern,),
                    description=f"path prefix {prefix!r}",
                )
            )

        # ------------------------------------------------------------------
        # 4 + 5. ABAC conditions from all direct_access grants
        # ------------------------------------------------------------------
        for grant in direct_accesses:
            if intent not in grant.actions:
                continue
            for attr_key, expected in grant.abac_conditions.items():
                if isinstance(expected, dict) and "$exclude" in expected:
                    excluded_vals = [str(v) for v in expected["$exclude"]]
                    pset = pset.append(
                        Predicate(
                            sql=f"value_json->>{attr_key!r} != ALL($1::text[])",
                            params=(excluded_vals,),
                            description=f"exclude {attr_key} in {excluded_vals}",
                        )
                    )
                else:
                    pset = pset.append(
                        Predicate(
                            sql=f"value_json->>{attr_key!r} = $1",
                            params=(str(expected),),
                            description=f"{attr_key} = {expected!r}",
                        )
                    )

        # ------------------------------------------------------------------
        # 6. Extra caller-supplied filters
        # ------------------------------------------------------------------
        if extra_filters:
            for field_name, value in extra_filters.items():
                pset = pset.append(
                    Predicate(
                        sql=f"value_json->>{field_name!r} = $1",
                        params=(str(value),),
                        description=f"extra filter {field_name}={value!r}",
                    )
                )

        return pset
