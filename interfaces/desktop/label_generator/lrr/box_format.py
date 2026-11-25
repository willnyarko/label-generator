"""Map the stock names in the window to the physical label sheets."""

from ..engine.lrr.box_kinds import STOCKS as ENGINE_STOCKS, classify_box_kind, group_boxes_by_kind
from ..engine.models.lrr import BoxLRR
from ..projections.options import BoxFormat, BoxFormatChoice, stock_kind

STOCKS = {"default" if kind == "full" else kind: stock for kind, stock in ENGINE_STOCKS.items()}


def classify_box_format(container_type: str | None) -> BoxFormat:
    kind = classify_box_kind(container_type)
    return "default" if kind == "full" else kind


def group_boxes_by_format(
    boxes: list[BoxLRR], *, choice: BoxFormatChoice = "auto"
) -> dict[BoxFormat, list[BoxLRR]]:
    groups = group_boxes_by_kind(boxes, choice=stock_kind(choice))
    return {"default" if kind == "full" else kind: rows for kind, rows in groups.items() if rows}
