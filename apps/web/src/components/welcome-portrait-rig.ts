const WIDTH = 1024;
const HEIGHT = 1536;

function smoothstep(from: number, to: number, value: number) {
  const t = Math.max(0, Math.min(1, (value - from) / (to - from)));
  return t * t * (3 - 2 * t);
}

/** Rest coordinates and bone weights. The entire seat/hand band stays rigid. */
export function createWelcomePortraitMesh() {
  const vertices: number[] = [];
  const add = (x: number, y: number) => {
    const torso = 1 - smoothstep(.4, .59, y);
    const legs = smoothstep(.635, .76, y) * (1 - smoothstep(.47, .55, x));
    const seam = .36 - Math.max(0, y - .6) * .35;
    const right = smoothstep(seam - .035, seam + .035, x);
    vertices.push(x, y, torso, legs * (1 - right), legs * right);
  };
  const columns = 32;
  const rows = 64;
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      const x = column / columns, x1 = (column + 1) / columns;
      const y = row / rows, y1 = (row + 1) / rows;
      add(x, y); add(x1, y); add(x, y1);
      add(x, y1); add(x1, y); add(x1, y1);
    }
  }
  return new Float32Array(vertices);
}

const VERTEX = `
attribute vec2 a_uv;
attribute vec3 a_weights;
uniform vec3 u_angles;
varying vec2 v_uv;
vec2 turn(vec2 point, vec2 pivot, float angle) {
  float c = cos(angle), s = sin(angle);
  vec2 p = point - pivot;
  return pivot + vec2(c * p.x - s * p.y, s * p.x + c * p.y);
}
void main() {
  vec2 size = vec2(1024., 1536.);
  vec2 p = a_uv * size;
  vec2 posed = p;
  posed += (turn(p, vec2(.55, .6) * size, u_angles.x) - p) * a_weights.x;
  posed += (turn(p, vec2(.26, .62) * size, u_angles.y) - p) * a_weights.y;
  posed += (turn(p, vec2(.4, .63) * size, u_angles.z) - p) * a_weights.z;
  gl_Position = vec4(posed.x / size.x * 2. - 1., 1. - posed.y / size.y * 2., 0., 1.);
  v_uv = a_uv;
}`;

const FRAGMENT = `
precision mediump float;
uniform sampler2D u_image;
varying vec2 v_uv;
void main() { gl_FragColor = texture2D(u_image, v_uv); }
`;

export type WelcomePortraitRig = { draw: (seconds: number) => void; dispose: () => void };

/** A single texture and static mesh; only three joint angles change per frame. */
export function createWelcomePortraitRig(canvas: HTMLCanvasElement, image: HTMLImageElement): WelcomePortraitRig | null {
  const gl = canvas.getContext("webgl", {
    alpha: true, premultipliedAlpha: true, antialias: false,
    depth: false, stencil: false, powerPreference: "low-power",
  });
  if (!gl) return null;

  const shaders: WebGLShader[] = [];
  let program: WebGLProgram | null = null;
  let buffer: WebGLBuffer | null = null;
  let texture: WebGLTexture | null = null;
  const dispose = () => {
    gl.deleteTexture(texture);
    gl.deleteBuffer(buffer);
    gl.deleteProgram(program);
    shaders.forEach(shader => gl.deleteShader(shader));
  };
  try {
    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type);
      if (!shader) throw new Error("Portrait shader unavailable");
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error("Portrait shader compilation failed");
      return shader;
    };
    program = gl.createProgram();
    if (!program) throw new Error("Portrait program unavailable");
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Portrait shader linking failed");
    gl.useProgram(program);

    const mesh = createWelcomePortraitMesh();
    buffer = gl.createBuffer();
    texture = gl.createTexture();
    if (!buffer || !texture) throw new Error("Portrait resources unavailable");
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, mesh, gl.STATIC_DRAW);
    const uv = gl.getAttribLocation(program, "a_uv");
    const weights = gl.getAttribLocation(program, "a_weights");
    gl.enableVertexAttribArray(uv);
    gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, 20, 0);
    gl.enableVertexAttribArray(weights);
    gl.vertexAttribPointer(weights, 3, gl.FLOAT, false, 20, 8);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    gl.uniform1i(gl.getUniformLocation(program, "u_image"), 0);
    const angles = gl.getUniformLocation(program, "u_angles");
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    gl.viewport(0, 0, WIDTH, HEIGHT);
    gl.clearColor(0, 0, 0, 0);
    return {
      draw(seconds) {
        // Periods divide the 120-second Anime.js clock, keeping its loop seamless.
        const tau = Math.PI * 2;
        gl.uniform3f(angles,
          Math.sin(seconds * tau / 8) * .007,
          Math.sin(seconds * tau / 5) * .022,
          Math.sin(seconds * tau / 6) * .018,
        );
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.drawArrays(gl.TRIANGLES, 0, mesh.length / 5);
      },
      dispose,
    };
  } catch {
    dispose();
    return null;
  }
}
