// Canonical 60% Apple contour, moved unchanged from index.html.
const appleSquarePath = 'M1.0000 0.5000C1.0000 0.6017 1.0000 0.6608 0.9734 0.7578C0.9571 0.8095 0.9320 0.8554 0.8937 0.8937C0.8554 0.9320 0.8095 0.9571 0.7578 0.9734C0.6608 1.0000 0.6017 1.0000 0.5000 1.0000C0.3983 1.0000 0.3392 1.0000 0.2422 0.9734C0.1905 0.9571 0.1446 0.9320 0.1063 0.8937C0.0680 0.8554 0.0429 0.8095 0.0266 0.7578C0.0000 0.6608 0.0000 0.6017 0.0000 0.5000C0.0000 0.3983 0.0000 0.3392 0.0266 0.2422C0.0429 0.1905 0.0680 0.1446 0.1063 0.1063C0.1446 0.0680 0.1905 0.0429 0.2422 0.0266C0.3392 0.0000 0.3983 0.0000 0.5000 0.0000C0.6017 0.0000 0.6608 0.0000 0.7578 0.0266C0.8095 0.0429 0.8554 0.0680 0.8937 0.1063C0.9320 0.1446 0.9571 0.1905 0.9734 0.2422C1.0000 0.3392 1.0000 0.3983 1.0000 0.5000Z';
const originalContours = [
  {
    "id": "square",
    "width": 1,
    "height": 1,
    "path": appleSquarePath
  },
  {
    "id": "start",
    "width": 199,
    "height": 81,
    "path": "M40.5 81H158.5C172.973 81 180.21 81 185.698 78.0941C190.127 75.7491 193.749 72.1272 196.094 67.6982C199 62.21 199 58.9274 199 52.3622C199 29.9807 199 18.79 196.094 13.3018C193.749 8.87281 190.127 5.25086 185.698 2.90586C180.21 0 172.973 0 158.5 0H40.5C26.0266 0 18.79 0 13.3018 2.90586C8.87281 5.25086 5.25086 8.87281 2.90586 13.3018C0 18.79 0 26.0266 0 40.5C0 54.9734 0 62.21 2.90586 67.6982C5.25086 72.1272 8.87281 75.749 13.3018 78.0941C18.79 81 26.0266 81 40.5 81Z"
  }
];

/** Keep every Apple corner control point; insert straight lines between the caps. */
export function squareButtonContour(width: number, height: number): string {
  const middle = width - height;
  let previousX = 1;
  return appleSquarePath.replace(/([MCZ])([^MCZ]*)/g, (_segment, command: string, values: string) => {
    if (command === "Z") return "Z";
    const points = (values.match(/\d+(?:\.\d+)?/g) ?? []).map(Number);
    const endX = points[points.length - 2], endY = points[points.length - 1];
    const rightCap = previousX > .5;
    const mapped = points.map((value, index) => Number((value * height +
      (index % 2 === 0 && (value > .5 || (value === .5 && rightCap)) ? middle : 0)).toFixed(5)));
    const straight = endX === .5 ? `L${height / 2 + (rightCap ? 0 : middle)} ${endY * height}` : "";
    previousX = endX;
    return `${command}${mapped.join(" ")}${straight}`;
  });
}

const contours = [
  ...originalContours,
  ...[
    { id: "media", width: 132, height: 66 },
    { id: "finish", width: 223, height: 81 },
    { id: "new", width: 198, height: 66 },
  ].map(contour => ({ ...contour, path: squareButtonContour(contour.width, contour.height) })),
];

export function MaterialButtonContours() {
  return <svg width="0" height="0" aria-hidden="true" style={{ position: "absolute", pointerEvents: "none" }}><defs>
    <clipPath id="apple-squircle-square" clipPathUnits="objectBoundingBox"><path d={appleSquarePath} /></clipPath>
    {contours.map(({ id, width, height, path }) => <clipPath key={id} id={`iris-material-${id}`} clipPathUnits="objectBoundingBox"><path d={path} transform={`scale(${1 / width} ${1 / height})`} /></clipPath>)}
  </defs></svg>;
}
