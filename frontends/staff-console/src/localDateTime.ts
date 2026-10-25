/** Parse explicitly typed 24-hour local time without accepting browser date guesses. */
export function localDateTimeToISO(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!match) throw new Error("Enter a date and time as YYYY-MM-DD HH:mm:ss (24-hour time).");
  const [, year, month, day, hour, minute, second = "00"] = match;
  const parsed = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}`);
  const parts = [parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate(), parsed.getHours(), parsed.getMinutes(), parsed.getSeconds()];
  const expected = [year, month, day, hour, minute, second].map(Number);
  if (Number.isNaN(parsed.getTime()) || parts.some((part, index) => part !== expected[index])) {
    throw new Error("Enter a valid local date and time; check the date and daylight-saving clock change.");
  }
  return parsed.toISOString();
}
