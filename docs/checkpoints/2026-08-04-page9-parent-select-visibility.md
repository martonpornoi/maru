# Page 9 Parent Department selection visibility

Date: 2026-08-04

## Outcome

The Create Department and Department editor forms now visibly retain the
selected Parent Department label.

## Defect

Django Admin's base stylesheet fixed native `select` elements at 30 pixels
high. Maru's shared baseline form styling simultaneously added 12 pixels of
padding above and below the select text. The browser changed and submitted the
correct selected value, but the closed control had too little content height
to paint its label. This made a successful selection appear unchanged.

The persisted hierarchy and option filtering were correct. The reproduced
dataset contained active sibling Departments below Events, and the projector
offered Events as a valid parent.

## Correction

`core/baseline.css` now scopes single-select sizing to Maru baseline forms:

- `height: auto` overrides the fixed Django Admin height;
- `min-height: 2.75rem` preserves a clear and usable control target; and
- multiple-select sizing remains governed by its existing 12rem rule.

No JavaScript replacement control was introduced. Native pointer, keyboard,
form, and accessibility semantics remain intact.

## Verification

- static style regression: passed;
- Page 9 parent-choice integration regression: passed;
- Page 9 create/update/retire/delete lifecycle regression: passed;
- Ruff lint and format checks for the new test: passed;
- authenticated browser reproduction before the fix: selected value was
  Events while the closed field rendered blank at 30 pixels;
- authenticated browser verification after the fix: selected label
  `Events — top-level — option 1` rendered visibly at 47 pixels with a
  44-pixel minimum.

The browser test did not submit the form, and the existing Department dataset
was not modified.
