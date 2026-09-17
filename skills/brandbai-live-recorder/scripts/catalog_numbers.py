"""Candidate link numbers, never product identity or confirmed page numbers."""


def number_hints(rows, complete):
    missing = [i for i, row in enumerate(rows) if row.get('list_position') is None]
    if not complete or len(rows) < 3 or len(missing) != 1:
        return {}
    index = missing[0]
    # Even multiple clues do not exclude a promoted explaining row.
    if rows[index].get('explaining') is not True or sum(r.get('explaining') is True for r in rows) != 1:
        return {}
    if any(r.get('list_position') != i + 1 for i, r in enumerate(rows) if i != index):
        return {}
    return {index: dict(candidate=index + 1, status='inferred_unverified',
                        evidence=['single_missing_number', 'other_numbers_contiguous',
                                  'row_order_consistent', 'explaining_label'],
                        warning='explaining_item_may_be_promoted')}
