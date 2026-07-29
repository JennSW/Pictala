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
      onSelect={(date) => onSelect(date ? format(date, ISO_FORMAT) : null)}
      disabled={(date) => !availableDates.has(format(date, ISO_FORMAT))}
      aria-label="Jump to a specific outing date"
    />
  );
}
