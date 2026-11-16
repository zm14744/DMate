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
    moduli = [_integer(modulus, 1, 30) for modulus in moduli]
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
        table, labels = _cyclic_product([_integer(spec.get("parameter"), 1, 24)], lambda a, b: a + b)
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
        size = _integer(len(values) if isinstance(values, list) else None, 1, 16)
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


def _generator_indices(labels, generators):
    if not isinstance(generators, list) or len(generators) > 8:
        raise AlgebraStructureError("specify up to eight generator indices")
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
            converted.append(_integer(item, 0, len(labels) - 1))
    if len(set(converted)) != len(converted):
        raise AlgebraStructureError("duplicate generators")
    return converted


def cayley_structure(group, generators):
    table, labels, identity = group_structure(group)
    if len(table) == 1 and generators is None:
        generators = []
    generators = _generator_indices(labels, generators)
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


def semigroup_cayley_structure(spec, generators, *, require_identity=False):
    if not isinstance(spec, dict):
        raise AlgebraStructureError("missing finite semigroup")
    family = spec.get("family")
    if family in ("modular_multiplication", "left_zero", "right_zero"):
        size = _integer(spec.get("parameter"), 1, 24)
        table = [[(left * right) % size if family == "modular_multiplication"
                  else left if family == "left_zero" else right
                  for right in range(size)] for left in range(size)]
        labels = [str(index) for index in range(size)]
    elif family == "table":
        values = spec.get("multiplication_table")
        size = _integer(len(values) if isinstance(values, list) else None, 1, 16)
        table = _table(values, size)
        labels = _labels(spec.get("labels"), size)
    else:
        raise AlgebraStructureError("unsupported finite semigroup")
    if any(table[table[a][b]][c] != table[a][table[b][c]]
           for a in range(size) for b in range(size) for c in range(size)):
        raise AlgebraStructureError("operation is not associative")
    identities = [item for item in range(size)
                  if all(table[item][other] == table[other][item] == other for other in range(size))]
    if require_identity and len(identities) != 1:
        raise AlgebraStructureError("monoid must have an identity")
    indices = _generator_indices(labels, generators)
    members = {identities[0], *indices} if require_identity else set(indices)
    while True:
        expanded = members | {table[a][b] for a in members for b in members}
        if expanded == members:
            break
        members = expanded
    if len(members) != size:
        raise AlgebraStructureError("generators do not generate the structure")
    return labels, [(index, table[index][generator], labels[generator])
                    for index in range(size) for generator in indices]


def _finite_field(order):
    order = _integer(order, 2, 24)
    if all(order % divisor for divisor in range(2, math.isqrt(order) + 1)):
        addition, labels = _cyclic_product([order], lambda a, b: a + b)
        multiplication, _ = _cyclic_product([order], lambda a, b: a * b)
        return addition, multiplication, labels
    extensions = {4: (2, [1, 1, 1]), 8: (2, [1, 1, 0, 1]),
                  9: (3, [1, 0, 1]), 16: (2, [1, 1, 0, 0, 1])}
    if order not in extensions:
        raise AlgebraStructureError("finite field order must be a supported prime power")
    prime, polynomial = extensions[order]
    degree = len(polynomial) - 1
    digits = [[(value // prime ** index) % prime for index in range(degree)] for value in range(order)]
    encode = lambda coefficients: sum(value % prime * prime ** index for index, value in enumerate(coefficients))
    addition = [[encode([(a + b) % prime for a, b in zip(left, right)])
                 for right in digits] for left in digits]
    multiplication = []
    for left in digits:
        row = []
        for right in digits:
            product = [0] * (2 * degree - 1)
            for a, coefficient in enumerate(left):
                for b, other in enumerate(right):
                    product[a + b] = (product[a + b] + coefficient * other) % prime
            for exponent in range(len(product) - 1, degree - 1, -1):
                factor = product[exponent]
                for index, coefficient in enumerate(polynomial):
                    position = exponent - degree + index
                    product[position] = (product[position] - factor * coefficient) % prime
            row.append(encode(product[:degree]))
        multiplication.append(row)
    labels = []
    for coefficients in digits:
        terms = []
        for exponent in range(degree - 1, -1, -1):
            coefficient = coefficients[exponent]
            if not coefficient:
                continue
            power = "" if exponent == 0 else "α" if exponent == 1 else "α^" + str(exponent)
            terms.append((str(coefficient) if exponent == 0 or coefficient != 1 else "") + power)
        labels.append("+".join(terms) or "0")
    return addition, multiplication, labels


def ring_structure(spec, *, require_commutative=False):
    if not isinstance(spec, dict):
        raise AlgebraStructureError("missing finite ring")
    family = spec.get("family")
    if family in ("zn", "product_zn"):
        moduli = [spec.get("parameter")] if family == "zn" else spec.get("moduli")
        addition, labels = _cyclic_product(moduli, lambda a, b: a + b)
        multiplication, _ = _cyclic_product(moduli, lambda a, b: a * b)
    elif family == "finite_field":
        addition, multiplication, labels = _finite_field(spec.get("parameter"))
    elif family == "table":
        values = spec.get("addition_table")
        size = _integer(len(values) if isinstance(values, list) else None, 1, 16)
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
            if require_commutative and multiplication[a][b] != multiplication[b][a]:
                raise AlgebraStructureError("ring must be commutative")
            for c in range(size):
                if (multiplication[multiplication[a][b]][c] != multiplication[a][multiplication[b][c]]
                        or multiplication[a][addition[b][c]] != addition[multiplication[a][b]][multiplication[a][c]]
                        or multiplication[addition[a][b]][c] != addition[multiplication[a][c]][multiplication[b][c]]):
                    raise AlgebraStructureError("invalid ring laws")
    return addition, multiplication, labels, zero


def ideal_structure(ring):
    addition, multiplication, labels, zero = ring_structure(ring)
    structures = [(members, generators) for members, generators in subgroups(addition, zero)
                  if all(multiplication[scalar][item] in members and multiplication[item][scalar] in members
                         for scalar in range(len(addition)) for item in members)]
    names = ["{" + labels[zero] + "}" if len(members) == 1 else "R" if len(members) == len(addition)
             else "(" + ", ".join(labels[index] for index in generators) + ")"
             for members, generators in structures]
    relations = [(left, right) for left, (lower, _) in enumerate(structures)
                 for right, (upper, _) in enumerate(structures) if lower < upper]
    return names, relations


def zero_divisor_structure(ring):
    _, multiplication, labels, zero = ring_structure(ring, require_commutative=True)
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
