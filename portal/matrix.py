from .calculation import BANDS, METHODS, format_number


def matrix_rows(rows, hazards, revision):
    calculate = METHODS[revision.method_id]
    probabilities = {
        (row, hazard): value
        for row, hazard, value in revision.probabilities.values_list("row_id", "hazard_id", "value")
    }
    positive = set()
    matrix = []
    for row in rows:
        cells = []
        for hazard in hazards:
            probability = probabilities.get((row.pk, hazard.pk))
            risk, band = calculate(hazard.severity, probability)
            if risk is not None and risk > 0:
                positive.add(hazard.pk)
            cells.append({
                "column": hazard.pk, "p": format_number(probability), "r": format_number(risk),
                "band": band, "band_label": BANDS.get(band, ""),
            })
        matrix.append((row, cells))
    columns = [(hazard, format_number(hazard.severity), hazard.pk in positive) for hazard in hazards]
    return matrix, columns
