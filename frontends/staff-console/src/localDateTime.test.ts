import { describe, expect, it } from "vitest";
import { localDateTimeToISO } from "./localDateTime";

describe("explicit 24-hour local date entry", () => {
  it("preserves local time and nonzero seconds", () => {
    const value = localDateTimeToISO("2031-06-06 19:05:27");
    const date = new Date(value);
    expect([date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(), date.getMinutes(), date.getSeconds()])
      .toEqual([2031, 6, 6, 19, 5, 27]);
  });
  it("accepts existing canonical local-minute input", () => {
    expect(localDateTimeToISO("2031-06-06T10:00")).toBe(localDateTimeToISO("2031-06-06 10:00:00"));
  });
  it.each(["2031-02-30 10:00:00", "2031-06-06 25:00:00", "06/06/2031 10:00 AM", "2031-06-06 10:00:00Z", "2031-06-06", ""])
    ("rejects invalid or ambiguous format %s", (value) => {
      expect(() => localDateTimeToISO(value)).toThrow(/Enter a/);
    });
});
