"""Groups checklists into outings.

See docs/USER_STORIES.md, "Story: Group checklists by date + Location
ID". A real trip often produces several separate eBird checklist
submissions (one per species logged separately, one per observer, etc.)
-- grouping by date + eBird Location ID treats those as a single outing,
so a photo doesn't show up as an unresolved candidate across checklists
it doesn't belong to. A checklist with no `location_id` (leftover sample
data, or a personal location eBird didn't assign one to) is its own
single-checklist group rather than being silently dropped.
"""
from sqlalchemy.orm import Session

from app.models import Checklist


def _group_key(checklist: Checklist) -> tuple[str, str]:
    if checklist.location_id:
        return (checklist.date, checklist.location_id)
    return (checklist.date, f"_checklist_{checklist.id}")


def group_checklists(checklists: list[Checklist]) -> list[list[Checklist]]:
    """Group a list of checklists by (date, location_id). Order of groups
    follows first appearance in the input list; order within a group is
    preserved too."""
    groups: dict[tuple[str, str], list[Checklist]] = {}
    for c in checklists:
        groups.setdefault(_group_key(c), []).append(c)
    return list(groups.values())


def get_checklist_group(db: Session, checklist: Checklist) -> list[Checklist]:
    """All checklists sharing `checklist`'s date + location_id (including
    itself). A checklist with no location_id is its own group of one."""
    if not checklist.location_id:
        return [checklist]
    return (
        db.query(Checklist)
        .filter(Checklist.date == checklist.date, Checklist.location_id == checklist.location_id)
        .all()
    )
