import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const playerRoot = path.resolve(scriptDir, "..");
const workspaceRoot = path.resolve(playerRoot, "..");
const sourcePath = path.join(workspaceRoot, "assets", "iris-logo.svg");
const sceneDir = path.join(
  playerRoot,
  "public",
  "projects",
  "iris-loader",
  "scene-1",
);
const outputPath = path.join(sceneDir, "lottie.json");
const orbitSceneDir = path.join(
  playerRoot,
  "public",
  "projects",
  "iris-loader",
  "scene-2",
);
const orbitOutputPath = path.join(orbitSceneDir, "lottie.json");

const source = fs.readFileSync(sourcePath, "utf8");
const pathTags = [...source.matchAll(/<path\b[^>]*\sd="([^"]+)"[^>]*>/g)].map(
  (match) => ({ tag: match[0], d: match[1] }),
);

if (pathTags.length !== 8) {
  throw new Error(`Expected 8 SVG paths, found ${pathTags.length}`);
}

function parsePath(d) {
  const tokens =
    d.match(/[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g) ?? [];
  const vertices = [];
  const incoming = [];
  const outgoing = [];
  let cursor = 0;
  let command = "";
  let current = [0, 0];
  let start = [0, 0];

  const number = () => {
    const token = tokens[cursor++];
    if (token === undefined || /^[A-Za-z]$/.test(token)) {
      throw new Error(`Malformed path near token ${cursor - 1}: ${d}`);
    }
    return Number(token);
  };

  const addVertex = (point, inTangent = [0, 0]) => {
    vertices.push(point);
    incoming.push(inTangent);
    outgoing.push([0, 0]);
    current = point;
  };

  while (cursor < tokens.length) {
    if (/^[A-Za-z]$/.test(tokens[cursor])) command = tokens[cursor++];
    if (!command) throw new Error(`Missing SVG command in: ${d}`);

    if (command === "M") {
      const point = [number(), number()];
      addVertex(point);
      start = point;
      command = "L";
    } else if (command === "L") {
      addVertex([number(), number()]);
    } else if (command === "H") {
      addVertex([number(), current[1]]);
    } else if (command === "V") {
      addVertex([current[0], number()]);
    } else if (command === "C") {
      const control1 = [number(), number()];
      const control2 = [number(), number()];
      const end = [number(), number()];
      outgoing[outgoing.length - 1] = [
        control1[0] - current[0],
        control1[1] - current[1],
      ];
      addVertex(end, [control2[0] - end[0], control2[1] - end[1]]);
    } else if (command === "Z" || command === "z") {
      current = start;
      command = "";
    } else {
      throw new Error(`Unsupported SVG path command "${command}"`);
    }
  }

  return { c: true, v: vertices, i: incoming, o: outgoing };
}

const parsedPaths = pathTags.map(({ d }) => parsePath(d));

const rgba = (hex) => {
  const value = hex.replace("#", "");
  return [
    Number.parseInt(value.slice(0, 2), 16) / 255,
    Number.parseInt(value.slice(2, 4), 16) / 255,
    Number.parseInt(value.slice(4, 6), 16) / 255,
    1,
  ];
};

const staticProp = (k) => ({ a: 0, k });
const linearOut = { x: [1 / 3], y: [1 / 3] };
const linearIn = { x: [2 / 3], y: [2 / 3] };

function sampledProperty(valueAtFrame) {
  const samples = [];
  for (let frame = 0; frame <= 120; frame += 1) {
    samples.push({ frame, value: valueAtFrame(frame) });
  }

  const keyframes = [];
  for (let index = 0; index < samples.length; index += 1) {
    const { frame, value } = samples[index];
    const keyframe = { t: frame, s: value };
    if (index < samples.length - 1) {
      keyframe.e = samples[index + 1].value;
      keyframe.i = linearIn;
      keyframe.o = linearOut;
    }
    keyframes.push(keyframe);
  }
  return { a: 1, k: keyframes };
}

function layerTransform({
  anchor,
  position,
  positionAtFrame,
  rotationAtFrame,
  opacityAtFrame,
}) {
  const baseScale = 165;
  return {
    o: opacityAtFrame
      ? sampledProperty((frame) => [opacityAtFrame(frame)])
      : staticProp(100),
    r: rotationAtFrame
      ? sampledProperty((frame) => [rotationAtFrame(frame)])
      : staticProp(0),
    a: staticProp([...anchor, 0]),
    s: staticProp([baseScale, baseScale, 100]),
    p: positionAtFrame
      ? sampledProperty((frame) => [...positionAtFrame(frame), 0])
      : staticProp([...position, 0]),
  };
}

function raisedPulse(frame, center, halfWidth) {
  const distance = Math.abs(frame - center);
  if (distance >= halfWidth) return 0;
  const progress = (frame - (center - halfWidth)) / (halfWidth * 2);
  return 0.5 - 0.5 * Math.cos(progress * Math.PI * 2);
}

function mixColor(from, to, amount) {
  return from.map((channel, index) => {
    if (index === 3) return 1;
    return channel + (to[index] - channel) * amount;
  });
}

const identityTransform = {
  ty: "tr",
  p: staticProp([0, 0]),
  a: staticProp([0, 0]),
  s: staticProp([100, 100]),
  r: staticProp(0),
  o: staticProp(100),
  sk: staticProp(0),
  sa: staticProp(0),
};

function shape(pathData, name) {
  return {
    ty: "sh",
    nm: name,
    ks: staticProp(pathData),
    hd: false,
  };
}

function solidGroup(pathData, name, colorAtFrame) {
  const baseColor = rgba("#2C264E");
  const color = colorAtFrame
    ? sampledProperty((frame) => colorAtFrame(frame))
    : staticProp(baseColor);
  return {
    ty: "gr",
    nm: name,
    it: [
      shape(pathData, `${name} Path`),
      { ty: "fl", nm: `${name} Fill`, c: color, o: staticProp(100), r: 1 },
      {
        ty: "st",
        nm: `${name} Stroke`,
        c: color,
        o: staticProp(100),
        w: staticProp(3),
        lc: 1,
        lj: 1,
        ml: 4,
      },
      { ...identityTransform, nm: `${name} Transform` },
    ],
    hd: false,
  };
}

function gradientGroup(pathData, name, gradient) {
  const [startColor, endColor] = gradient.colors.map((color) => rgba(color));
  return {
    ty: "gr",
    nm: name,
    it: [
      shape(pathData, `${name} Path`),
      {
        ty: "gf",
        nm: `${name} Gradient`,
        o: staticProp(100),
        r: 1,
        bm: 0,
        g: {
          p: 2,
          k: staticProp([
            0,
            startColor[0],
            startColor[1],
            startColor[2],
            1,
            endColor[0],
            endColor[1],
            endColor[2],
          ]),
        },
        s: staticProp(gradient.start),
        e: staticProp(gradient.end),
        t: 1,
        h: staticProp(0),
        a: staticProp(0),
      },
      { ...identityTransform, nm: `${name} Transform` },
    ],
    hd: false,
  };
}

function shapeLayer({ index, name, shapes, transform }) {
  return {
    ddd: 0,
    ind: index,
    ty: 4,
    nm: name,
    sr: 1,
    ks: transform,
    ao: 0,
    shapes,
    ip: 0,
    op: 120,
    st: 0,
    bm: 0,
  };
}

const contentScale = 1.65;
const contentOrigin = [
  (512 - 261 * contentScale) / 2,
  (512 - 94 * contentScale) / 2,
];
const sourceToComp = ([x, y]) => [
  contentOrigin[0] + x * contentScale,
  contentOrigin[1] + y * contentScale,
];
const compOffset = ([x, y]) => [x * contentScale, y * contentScale];

function pathBounds(pathData) {
  const xs = [];
  const ys = [];
  for (let index = 0; index < pathData.v.length; index += 1) {
    const vertex = pathData.v[index];
    const incomingPoint = [
      vertex[0] + pathData.i[index][0],
      vertex[1] + pathData.i[index][1],
    ];
    const outgoingPoint = [
      vertex[0] + pathData.o[index][0],
      vertex[1] + pathData.o[index][1],
    ];
    xs.push(vertex[0], incomingPoint[0], outgoingPoint[0]);
    ys.push(vertex[1], incomingPoint[1], outgoingPoint[1]);
  }
  return {
    center: [
      (Math.min(...xs) + Math.max(...xs)) / 2,
      (Math.min(...ys) + Math.max(...ys)) / 2,
    ],
  };
}

const gradients = [
  {
    start: [41.2483, 5.05992],
    end: [69.4301, 67.7872],
    colors: ["#9B82CD", "#8D73BC"],
  },
  {
    start: [4.15691, 47.6054],
    end: [44.3387, 87.969],
    colors: ["#302A57", "#252044"],
  },
  {
    start: [55.4299, 88.1506],
    end: [95.4299, 57.6051],
    colors: ["#554781", "#67589A"],
  },
];

const petalSpecs = [
  {
    index: 3,
    name: "Iris Petal — Top",
    pathIndex: 5,
    gradientIndex: 0,
    center: 15,
    halfWidth: 15,
    sourceOffset: [0, 3.2],
    rotation: -1.1,
  },
  {
    index: 2,
    name: "Iris Petal — Lower Left",
    pathIndex: 6,
    gradientIndex: 1,
    center: 28,
    halfWidth: 16,
    sourceOffset: [2.7, -1.4],
    rotation: 1.35,
  },
  {
    index: 1,
    name: "Iris Petal — Lower Right",
    pathIndex: 7,
    gradientIndex: 2,
    center: 41,
    halfWidth: 17,
    sourceOffset: [-2.5, -2.1],
    rotation: -1.25,
  },
];

const petalLayers = petalSpecs.map((spec) =>
  (() => {
    const pathData = parsedPaths[spec.pathIndex];
    const anchor = pathBounds(pathData).center;
    const basePosition = sourceToComp(anchor);
    const offset = compOffset(spec.sourceOffset);
    const pulse = (frame) => raisedPulse(frame, spec.center, spec.halfWidth);
    return shapeLayer({
      index: spec.index,
      name: spec.name,
      shapes: [
        gradientGroup(
          pathData,
          spec.name,
          gradients[spec.gradientIndex],
        ),
      ],
      transform: layerTransform({
        anchor,
        position: basePosition,
        positionAtFrame: (frame) => {
          const amount = pulse(frame);
          return [
            basePosition[0] + offset[0] * amount,
            basePosition[1] + offset[1] * amount,
          ];
        },
        rotationAtFrame: (frame) => spec.rotation * pulse(frame),
      }),
    });
  })(),
);

const wordmarkSpecs = [
  {
    index: 4,
    name: "Wordmark — I",
    pathIndex: 0,
    center: 53,
    halfWidth: 15,
    lift: 5.2,
    drift: -0.8,
    colorAmount: 0.72,
  },
  {
    index: 5,
    name: "Wordmark — r",
    pathIndex: 1,
    center: 65,
    halfWidth: 15,
    lift: 6,
    drift: 0.4,
    colorAmount: 0.78,
  },
  {
    index: 6,
    name: "Wordmark — i Stem",
    pathIndex: 2,
    center: 77,
    halfWidth: 15,
    lift: 5.2,
    drift: 0.5,
    colorAmount: 0.76,
  },
  {
    index: 7,
    name: "Wordmark — i Dot",
    pathIndex: 3,
    center: 83,
    halfWidth: 17,
    lift: 10,
    drift: 2.2,
    colorAmount: 0.92,
  },
  {
    index: 8,
    name: "Wordmark — s",
    pathIndex: 4,
    center: 104,
    halfWidth: 16,
    lift: 6.2,
    drift: 0.9,
    colorAmount: 0.82,
  },
];

const wordmarkBase = rgba("#2C264E");
const wordmarkFocus = rgba("#66549A");

const wordmarkLayers = wordmarkSpecs.map((spec) => {
  const pathData = parsedPaths[spec.pathIndex];
  const anchor = pathBounds(pathData).center;
  const basePosition = sourceToComp(anchor);
  const pulse = (frame) => raisedPulse(frame, spec.center, spec.halfWidth);
  return shapeLayer({
    index: spec.index,
    name: spec.name,
    shapes: [
      solidGroup(pathData, spec.name, (frame) =>
        mixColor(
          wordmarkBase,
          wordmarkFocus,
          pulse(frame) * spec.colorAmount,
        ),
      ),
    ],
    transform: layerTransform({
      anchor,
      position: basePosition,
      positionAtFrame: (frame) => {
        const amount = pulse(frame);
        return [
          basePosition[0] + spec.drift * amount,
          basePosition[1] - spec.lift * amount,
        ];
      },
    }),
  });
});

const orbitPetalSpecs = [
  {
    index: 3,
    name: "Orbital Petal — Top",
    pathIndex: 5,
    gradientIndex: 0,
    phase: 0,
    radius: [4.4, 3.2],
    rotationAmplitude: 1.8,
  },
  {
    index: 2,
    name: "Orbital Petal — Lower Left",
    pathIndex: 6,
    gradientIndex: 1,
    phase: (Math.PI * 2) / 3,
    radius: [3.4, 4.2],
    rotationAmplitude: -1.55,
  },
  {
    index: 1,
    name: "Orbital Petal — Lower Right",
    pathIndex: 7,
    gradientIndex: 2,
    phase: (Math.PI * 4) / 3,
    radius: [4.1, 3.6],
    rotationAmplitude: 1.65,
  },
];

const orbitPetalLayers = orbitPetalSpecs.map((spec) => {
  const pathData = parsedPaths[spec.pathIndex];
  const anchor = pathBounds(pathData).center;
  const basePosition = sourceToComp(anchor);
  const radius = compOffset(spec.radius);
  const angleAtFrame = (frame) => (Math.PI * 2 * frame) / 120 + spec.phase;
  const startCos = Math.cos(spec.phase);
  const startSin = Math.sin(spec.phase);
  return shapeLayer({
    index: spec.index,
    name: spec.name,
    shapes: [
      gradientGroup(
        pathData,
        spec.name,
        gradients[spec.gradientIndex],
      ),
    ],
    transform: layerTransform({
      anchor,
      position: basePosition,
      positionAtFrame: (frame) => {
        if (frame === 0 || frame === 120) return basePosition;
        const angle = angleAtFrame(frame);
        return [
          basePosition[0] + radius[0] * (Math.cos(angle) - startCos),
          basePosition[1] + radius[1] * (Math.sin(angle) - startSin),
        ];
      },
      rotationAtFrame: (frame) => {
        if (frame === 0 || frame === 120) return 0;
        return (
          spec.rotationAmplitude *
          (Math.sin(angleAtFrame(frame)) - startSin)
        );
      },
    }),
  });
});

const orbitWordmarkLayers = wordmarkSpecs.map((spec) => {
  const pathData = parsedPaths[spec.pathIndex];
  const anchor = pathBounds(pathData).center;
  const basePosition = sourceToComp(anchor);
  const pulse = (frame) => raisedPulse(frame, spec.center, spec.halfWidth);
  return shapeLayer({
    index: spec.index,
    name: `${spec.name} — Orbital Response`,
    shapes: [
      solidGroup(pathData, spec.name, (frame) =>
        mixColor(
          wordmarkBase,
          wordmarkFocus,
          pulse(frame) * spec.colorAmount * 0.68,
        ),
      ),
    ],
    transform: layerTransform({
      anchor,
      position: basePosition,
      positionAtFrame: (frame) => {
        const amount = pulse(frame) * 0.62;
        return [
          basePosition[0] + spec.drift * amount,
          basePosition[1] - spec.lift * amount,
        ];
      },
    }),
  });
});

const lottie = {
  v: "5.12.2",
  fr: 60,
  ip: 0,
  op: 120,
  w: 512,
  h: 512,
  nm: "Iris Loader — Focus Transfer",
  ddd: 0,
  assets: [],
  layers: [
    petalLayers[2],
    petalLayers[1],
    petalLayers[0],
    wordmarkLayers[4],
    wordmarkLayers[3],
    wordmarkLayers[2],
    wordmarkLayers[1],
    wordmarkLayers[0],
  ],
};

const orbitLottie = {
  v: "5.12.2",
  fr: 60,
  ip: 0,
  op: 120,
  w: 512,
  h: 512,
  nm: "Iris Loader — Orbital Petals",
  ddd: 0,
  assets: [],
  layers: [
    orbitPetalLayers[2],
    orbitPetalLayers[1],
    orbitPetalLayers[0],
    orbitWordmarkLayers[4],
    orbitWordmarkLayers[3],
    orbitWordmarkLayers[2],
    orbitWordmarkLayers[1],
    orbitWordmarkLayers[0],
  ],
};

fs.mkdirSync(sceneDir, { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(lottie, null, 2)}\n`, "utf8");
fs.mkdirSync(orbitSceneDir, { recursive: true });
fs.writeFileSync(
  orbitOutputPath,
  `${JSON.stringify(orbitLottie, null, 2)}\n`,
  "utf8",
);

console.log(outputPath);
console.log(orbitOutputPath);
