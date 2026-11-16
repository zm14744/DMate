"""Small finite algebra structures, constructed and checked without model arithmetic.

The model selects a family or supplies complete operation tables.  It never
supplies subgroup/ideal membership or Cayley edges, which are derived here.
"""
from __future__ import annotations

import itertools
import math
import re


class AlgebraStructureError(ValueError):
    pass


def _integer(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise AlgebraStructureError("invalid parameter")
    return value


def _labels(values, size):
    if values is None:
        return [str(index) for index in range(size)]
    if (not isinstance(values, list) or len(values) != size
            or any(not isinstance(value, str) or not value.strip() or len(value) > 24
                   or any(ord(char) < 32 for char in value) for value in values)):
        raise AlgebraStructureError("invalid element labels")
    labels = [value.strip() for value in values]
    if len(set(labels)) != size:
        raise AlgebraStructureError("element labels must be distinct")
    return labels


def _table(value, size):
    if (not isinstance(value, list) or len(value) != size
            or any(not isinstance(row, list) or len(row) != size for row in value)):
        raise AlgebraStructureError("operation table must be square")
    return [[_integer(item, 0, size - 1) for item in row] for row in value]


def check_group(table, *, abelian=False):
    size = len(table)
    identities = [identity for identity in range(size)
                  if all(table[identity][item] == table[item][identity] == item for item in range(size))]
    if len(identities) != 1:
        raise AlgebraStructureError("group identity does not exist")
    identity = identities[0]
    if any(not any(table[item][other] == table[other][item] == identity for other in range(size))
           for item in range(size)):
        raise AlgebraStructureError("group inverses do not exist")
    if any(table[table[a][b]][c] != table[a][table[b][c]]
           for a in range(size) for b in range(size) for c in range(size)):
        raise AlgebraStructureError("operation is not associative")
    if abelian and any(table[a][b] != table[b][a] for a in range(size) for b in range(size)):
        raise AlgebraStructureError("addition is not commutative")
    return identity


def _cyclic_product(moduli, operation):
    if not isinstance(moduli, list) or not 1 <= len(moduli) <= 4:
        raise AlgebraStructureError("invalid cyclic factors")
    moduli = [_integer(modulus, 2, 30) for modulus in moduli]
    size = math.prod(moduli)
    if size > 24:
        raise AlgebraStructureError("at most 24 elements")
    elements = list(itertools.product(*(range(modulus) for modulus in moduli)))
    indices = {element: index for index, element in enumerate(elements)}
    table = [[indices[tuple(operation(a, b) % modulus for a, b, modulus in zip(left, right, moduli))]
              for right in elements] for left in elements]
    labels = [str(element[0]) if len(moduli) == 1 else "(" + ",".join(map(str, element)) + ")"
              for element in elements]
    return table, labels


def _permutation_label(permutation):
    visited, cycles = set(), []
    for start in range(len(permutation)):
        if start in visited:
            continue
        cycle, current = [], start
        while current not in visited:
            visited.add(current)
            cycle.append(str(current + 1))
            current = permutation[current]
        if len(cycle) > 1:
            cycles.append("(" + " ".join(cycle) + ")")
    return "".join(cycles) or "e"


def group_structure(spec):
    if not isinstance(spec, dict):
        raise AlgebraStructureError("missing finite group")
    family = spec.get("family")
    if family == "cyclic":
        table, labels = _cyclic_product([_integer(spec.get("parameter"), 2, 24)], lambda a, b: a + b)
    elif family == "product_cyclic":
        table, labels = _cyclic_product(spec.get("moduli"), lambda a, b: a + b)
    elif family == "klein":
        table, labels = _cyclic_product([2, 2], lambda a, b: a + b)
        labels = ["e", "a", "b", "ab"]
    elif family == "dihedral":
        # D_n is the symmetry group of a regular n-gon, of order 2n.
        parameter = _integer(spec.get("parameter"), 3, 12)
        elements = [(rotation, reflection) for reflection in range(2) for rotation in range(parameter)]
        indices = {element: index for index, element in enumerate(elements)}
        table = [[indices[((a + (-1 if b else 1) * c) % parameter, (b + d) % 2)]
                  for c, d in elements] for a, b in elements]
        labels = [(("e" if rotation == 0 else "r" if rotation == 1 else f"r^{rotation}")
                   if not reflection else ("s" if rotation == 0 else "rs" if rotation == 1 else f"r^{rotation}s"))
                  for rotation, reflection in elements]
    elif family == "symmetric":
        parameter = _integer(spec.get("parameter"), 2, 4)
        elements = list(itertools.permutations(range(parameter)))
        indices = {element: index for index, element in enumerate(elements)}
        table = [[indices[tuple(left[right[index]] for index in range(parameter))]
                  for right in elements] for left in elements]
        labels = [_permutation_label(permutation) for permutation in elements]
    elif family == "quaternion":
        # Entries are (sign, basis), basis 0=1, 1=i, 2=j, 3=k.
        basis = [[(1, 0), (1, 1), (1, 2), (1, 3)],
                 [(1, 1), (-1, 0), (1, 3), (-1, 2)],
                 [(1, 2), (-1, 3), (-1, 0), (1, 1)],
                 [(1, 3), (1, 2), (-1, 1), (-1, 0)]]
        elements = [(sign, item) for sign in (1, -1) for item in range(4)]
        indices = {element: index for index, element in enumerate(elements)}
        table = [[indices[(left_sign * right_sign * basis[left][right][0], basis[left][right][1])]
                  for right_sign, right in elements] for left_sign, left in elements]
        labels = ["1", "i", "j", "k", "−1", "−i", "−j", "−k"]
    elif family == "table":
        values = spec.get("multiplication_table")
        size = _integer(len(values) if isinstance(values, list) else None, 2, 16)
        table = _table(values, size)
        labels = _labels(spec.get("labels"), size)
    else:
        raise AlgebraStructureError("unsupported finite group family")
    return table, labels, check_group(table)


def generated_subgroup(table, identity, generators):
    members = {identity, *generators}
    while True:
        expanded = members | {table[a][b] for a in members for b in members}
        if members == expanded:
            return frozenset(members)
        members = expanded


def subgroups(table, identity, *, limit=80):
    trivial = frozenset({identity})
    found, pending = {trivial: ()}, [trivial]
    while pending:
        current = pending.pop(0)
        for item in range(len(table)):
            if item in current:
                continue
            generators = found[current] + (item,)
            result = generated_subgroup(table, identity, generators)
            if result not in found:
                if len(found) >= limit:
                    raise AlgebraStructureError("too many substructures")
                found[result] = generators
                pending.append(result)
    return sorted(found.items(), key=lambda row: (len(row[0]), sorted(row[0])))


def cayley_structure(group, generators):
    table, labels, identity = group_structure(group)
    if not isinstance(generators, list) or not 1 <= len(generators) <= 8:
        raise AlgebraStructureError("specify one to eight generator indices")
    exact_labels = {label: index for index, label in enumerate(labels)}
    normalized_labels = {}
    for index, label in enumerate(labels):
        normalized = re.sub(r"\s+", "", label).replace("−", "-")
        normalized_labels.setdefault(normalized, []).append(index)
    converted = []
    for item in generators:
        if isinstance(item, str):
            exact = item.strip()
            if exact in exact_labels:
                converted.append(exact_labels[exact])
            else:
                label = re.sub(r"\s+", "", exact).replace("−", "-")
                matches = normalized_labels.get(label, [])
                if len(matches) != 1:
                    raise AlgebraStructureError("unknown or ambiguous generator label")
                converted.append(matches[0])
        else:
            converted.append(_integer(item, 0, len(table) - 1))
    generators = converted
    if len(set(generators)) != len(generators) or identity in generators:
        raise AlgebraStructureError("invalid generators")
    if len(generated_subgroup(table, identity, generators)) != len(table):
        raise AlgebraStructureError("generators do not generate the group")
    edges = [(index, table[index][generator], labels[generator])
             for index in range(len(table)) for generator in generators]
    return labels, edges


def subgroup_structure(group):
    table, labels, identity = group_structure(group)
    structures = subgroups(table, identity)
    names = ["{" + labels[identity] + "}" if len(members) == 1 else "G" if len(members) == len(table)
             else "⟨" + ", ".join(labels[index] for index in generators) + "⟩"
             for members, generators in structures]
    relations = [(left, right) for left, (lower, _) in enumerate(structures)
                 for right, (upper, _) in enumerate(structures) if lower < upper]
    return names, relations


def ring_structure(spec):
    if not isinstance(spec, dict):
        raise AlgebraStructureError("missing finite ring")
    family = spec.get("family")
    if family in ("zn", "product_zn"):
        moduli = [spec.get("parameter")] if family == "zn" else spec.get("moduli")
        addition, labels = _cyclic_product(moduli, lambda a, b: a + b)
        multiplication, _ = _cyclic_product(moduli, lambda a, b: a * b)
    elif family == "table":
        values = spec.get("addition_table")
        size = _integer(len(values) if isinstance(values, list) else None, 2, 16)
        addition = _table(values, size)
        multiplication = _table(spec.get("multiplication_table"), size)
        labels = _labels(spec.get("labels"), size)
    else:
        raise AlgebraStructureError("unsupported finite ring family")
    zero = check_group(addition, abelian=True)
    size = len(addition)
    if not any(all(multiplication[one][item] == multiplication[item][one] == item for item in range(size))
               for one in range(size)):
        raise AlgebraStructureError("ring must have an identity")
    for a in range(size):
        for b in range(size):
            if multiplication[a][b] != multiplication[b][a]:
                raise AlgebraStructureError("ring must be commutative")
            for c in range(size):
                if (multiplication[multiplication[a][b]][c] != multiplication[a][multiplication[b][c]]
                        or multiplication[a][addition[b][c]] != addition[multiplication[a][b]][multiplication[a][c]]):
                    raise AlgebraStructureError("invalid ring laws")
    return addition, multiplication, labels, zero


def ideal_structure(ring):
    addition, multiplication, labels, zero = ring_structure(ring)
    structures = [(members, generators) for members, generators in subgroups(addition, zero)
                  if all(multiplication[scalar][item] in members
                         for scalar in range(len(addition)) for item in members)]
    names = ["{" + labels[zero] + "}" if len(members) == 1 else "R" if len(members) == len(addition)
             else "(" + ", ".join(labels[index] for index in generators) + ")"
             for members, generators in structures]
    relations = [(left, right) for left, (lower, _) in enumerate(structures)
                 for right, (upper, _) in enumerate(structures) if lower < upper]
    return names, relations


def zero_divisor_structure(ring):
    _, multiplication, labels, zero = ring_structure(ring)
    members = [item for item in range(len(labels)) if item != zero
               and any(other != zero and multiplication[item][other] == zero for other in range(len(labels)))]
    if not members:
        raise AlgebraStructureError("ring has no nonzero zero divisors")
    edges = [(left, right) for left in range(len(members)) for right in range(left + 1, len(members))
             if multiplication[members[left]][members[right]] == zero]
    return [labels[index] for index in members], edges


def standard_lattice_structure(spec):
    if not isinstance(spec, dict):
        raise AlgebraStructureError("missing standard lattice")
    family = spec.get("family")
    if family == "boolean":
        rank = _integer(spec.get("parameter"), 1, 5)
        members = list(range(2 ** rank))
        labels = ["∅" if value == 0 else "{" + ",".join(str(bit + 1) for bit in range(rank) if value & (1 << bit)) + "}"
                  for value in members]
        relations = [(left, right) for left in members for right in members
                     if left != right and left & right == left]
    elif family == "divisors":
        parameter = _integer(spec.get("parameter"), 2, 120)
        members = [item for item in range(1, parameter + 1) if parameter % item == 0]
        labels = list(map(str, members))
        relations = [(left, right) for left, lower in enumerate(members) for right, upper in enumerate(members)
                     if lower != upper and upper % lower == 0]
    elif family == "diamond":
        labels = ["0", "a", "b", "c", "1"]
        relations = [(0, item) for item in (1, 2, 3)] + [(item, 4) for item in (1, 2, 3)]
    elif family == "pentagon":
        labels = ["0", "a", "b", "c", "1"]
        relations = [(0, 1), (1, 2), (2, 4), (0, 3), (3, 4)]
    else:
        raise AlgebraStructureError("unsupported standard lattice")
    return labels, relations
