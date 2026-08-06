import { DayPicker } from "react-day-picker";
import { format, parse } from "date-fns";
import "react-day-picker/dist/style.css";

const ISO_FORMAT = "yyyy-MM-dd";

interface DatePickerProps {
  availableDates: Set<string>;
  selected: string | null;
  onSelect: (date: string | null) => void;
}

// Date selection (see docs/USER_STORIES.md, "Story: Date selection").
// Only dates with at least one outing are selectable -- everything else
// is greyed out and disabled (not just styled differently), since a
// disabled state is what actually communicates "unavailable" to a
// screen reader, unlike a purely visual distinction (e.g. bold weight).
export default function DatePicker({ availableDates, selected, onSelect }: DatePickerProps) {
  const selectedDate = selected ? parse(selected, ISO_FORMAT, new Date()) : undefined;

  return (
    <DayPicker
      mode="single"
      selected={selectedDate}
      defaultMonth={new Date()}
      // DayPicker's single mode toggles a date off (fires onSelect with
      // undefined) if you click the already-selected one again -- that
      // clashes with there already being a dedicated "Clear date" button
      // as the one deliberate way to reset, and left the outings list
      // and the "Photos not on eBird" panel out of sync with each other
      // on a repeat click (issue found live 2026-08-06). Ignoring the
      // deselect event keeps a click on the current date a no-op instead.
      onSelect={(date) => date && onSelect(format(date, ISO_FORMAT))}
      disabled={(date) => !availableDates.has(format(date, ISO_FORMAT))}
      aria-label="Jump to a specific outing date"
    />
  );
}
