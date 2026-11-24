from decimal import localcontext


def format_number(value):
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def calculate_v1(gravity, probability):
    if probability is None:
        return None, ""
    with localcontext() as context:
        context.prec = 50
        result = gravity * probability
    if 1 <= result <= 2:
        return result, "low"
    if 3 <= result <= 7:
        return result, "medium"
    if result > 7:
        return result, "high"
    return result, ""


CURRENT_METHOD = "gxp-v1"
METHODS = {"gxp-v1": calculate_v1}
BANDS = {"low": "Bassa", "medium": "Media", "high": "Alta"}
