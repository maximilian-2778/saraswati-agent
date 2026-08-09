import { useEffect, useRef } from "react";

const WIDTH = 420;
const HEIGHT = 300;
const CENTER_X = 132;
const CENTER_Y = 78;
const RAY_COUNT = 52;
const NODE_COUNT = 28;

interface ProjectedPoint {
  x: number;
  y: number;
  z: number;
  scale: number;
}

type OrbitPlane = "disc" | "nodes";

export function ArchiveDiagram() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fanLines = Array.from({ length: 17 }, (_, index) => ({
    x: 210 + index * 12,
    y: 98 + index * 8.2,
  }));

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const drawingContext: CanvasRenderingContext2D = context;

    let frame = 0;
    let reduceMotion = false;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = WIDTH * pixelRatio;
    canvas.height = HEIGHT * pixelRatio;
    drawingContext.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const appShell = canvas.closest(".app-shell");

    function updateMotionPreference() {
      reduceMotion = motionQuery.matches || appShell?.classList.contains("reduce-motion") === true;
      cancelAnimationFrame(frame);
      if (reduceMotion) draw(0);
      else frame = requestAnimationFrame(render);
    }

    function render(time: number) {
      draw(time);
      frame = requestAnimationFrame(render);
    }

    function draw(time: number) {
      const paper = document.documentElement.dataset.saraswatiTheme === "paper";
      const line = paper ? [42, 78, 137] : [204, 170, 96];
      const background = paper ? "#f7f1e3" : "#181713";
      const phase = reduceMotion ? -0.35 : (time / 34_000) * Math.PI * 2;
      const nodePhase = reduceMotion ? 0.28 : -(time / 24_000) * Math.PI * 2;

      drawingContext.clearRect(0, 0, WIDTH, HEIGHT);
      drawRays(drawingContext, phase, line);
      drawOrbit(drawingContext, phase, 162, 132, line, 0.72, 1.05);
      drawOrbit(drawingContext, phase + 0.04, 151, 120, line, 0.52, 0.75);
      drawOrbit(drawingContext, phase - 0.03, 119, 91, line, 0.38, 0.55, true);
      drawOrbit(drawingContext, nodePhase, 145, 116, line, 0.32, 0.62, false, "nodes");
      drawNodes(drawingContext, nodePhase, background, paper);
    }

    const observer = new MutationObserver(updateMotionPreference);
    if (appShell) observer.observe(appShell, { attributes: true, attributeFilter: ["class"] });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-saraswati-theme"] });
    motionQuery.addEventListener("change", updateMotionPreference);
    updateMotionPreference();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      motionQuery.removeEventListener("change", updateMotionPreference);
    };
  }, []);

  return (
    <div className="archive-diagram" aria-hidden="true">
      <canvas ref={canvasRef} />
      <svg className="archive-ornament" viewBox="0 0 420 300">
        <g className="archive-rosette" transform="translate(132 78)">
          <circle r="35" />
          <circle className="fine" r="27" />
          <path d="M0-31 C7-21 7-10 0 0 C-7-10-7-21 0-31ZM31 0C21 7 10 7 0 0C10-7 21-7 31 0ZM0 31C-7 21-7 10 0 0C7 10 7 21 0 31ZM-31 0C-21-7-10-7 0 0C-10 7-21 7-31 0Z" />
          <circle className="archive-core" r="8" />
        </g>

        <g className="archive-fan">
          {fanLines.map((point, index) => (
            <line key={`fan-${index}`} x1="91" y1="86" x2={point.x} y2={point.y} />
          ))}
          <path className="archive-fan-edge" d="M91 86 Q244 118 402 236" />
          <path d="M91 86 Q226 153 365 264" />
          <path d="M91 86 Q202 184 317 286" />
          <path className="archive-data-line" d="M118 109L158 126L190 119L230 160L267 155L302 201L345 213" />
          <circle className="archive-node gold" cx="158" cy="126" r="3.8" />
          <circle className="archive-node blue" cx="230" cy="160" r="3.8" />
          <circle className="archive-node gold" cx="302" cy="201" r="3.8" />
        </g>
      </svg>
    </div>
  );
}

function project(angle: number, radiusX: number, radiusY: number, plane: OrbitPlane = "disc"): ProjectedPoint {
  const sourceX = Math.cos(angle) * radiusX;
  const sourceY = Math.sin(angle) * radiusY;
  // 射线盘和球环使用交叉的轨道平面，二者仍以同一个 Logo 为中心。
  const orientation = plane === "nodes"
    ? { x: 67, y: 19, z: 24 }
    : { x: 54, y: -11, z: -9 };
  const tiltX = orientation.x * Math.PI / 180;
  const tiltY = orientation.y * Math.PI / 180;
  const tiltZ = orientation.z * Math.PI / 180;

  const tiltedY = sourceY * Math.cos(tiltX);
  const depthAfterX = sourceY * Math.sin(tiltX);
  const tiltedX = sourceX * Math.cos(tiltY) + depthAfterX * Math.sin(tiltY);
  const depth = -sourceX * Math.sin(tiltY) + depthAfterX * Math.cos(tiltY);
  const rotatedX = tiltedX * Math.cos(tiltZ) - tiltedY * Math.sin(tiltZ);
  const rotatedY = tiltedX * Math.sin(tiltZ) + tiltedY * Math.cos(tiltZ);
  const focalLength = 510;
  const scale = focalLength / (focalLength - depth);

  return {
    x: CENTER_X + rotatedX * scale,
    y: CENTER_Y + rotatedY * scale,
    z: depth,
    scale,
  };
}

function drawRays(context: CanvasRenderingContext2D, phase: number, color: number[]) {
  for (let index = 0; index < RAY_COUNT; index += 1) {
    const angle = phase + (index / RAY_COUNT) * Math.PI * 2;
    const end = project(angle, 155, 126);
    const depth = clamp((end.z + 130) / 260, 0, 1);
    context.beginPath();
    context.moveTo(CENTER_X, CENTER_Y);
    context.lineTo(end.x, end.y);
    context.strokeStyle = rgba(color, 0.24 + depth * 0.42);
    context.lineWidth = (index % 5 === 0 ? 0.95 : 0.52) * end.scale;
    context.stroke();
  }
}

function drawOrbit(
  context: CanvasRenderingContext2D,
  phase: number,
  radiusX: number,
  radiusY: number,
  color: number[],
  opacity: number,
  width: number,
  dashed = false,
  plane: OrbitPlane = "disc",
) {
  const segments = 112;
  context.setLineDash(dashed ? [2, 3] : []);
  for (let index = 0; index < segments; index += 1) {
    const start = project(phase + (index / segments) * Math.PI * 2, radiusX, radiusY, plane);
    const end = project(phase + ((index + 1) / segments) * Math.PI * 2, radiusX, radiusY, plane);
    const depth = clamp(((start.z + end.z) / 2 + 135) / 270, 0, 1);
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.lineTo(end.x, end.y);
    context.strokeStyle = rgba(color, opacity * (0.42 + depth * 0.58));
    context.lineWidth = width * ((start.scale + end.scale) / 2);
    context.stroke();
  }
  context.setLineDash([]);
}

function drawNodes(context: CanvasRenderingContext2D, phase: number, border: string, paper: boolean) {
  const nodes = Array.from({ length: NODE_COUNT }, (_, index) => {
    const angle = phase + (index / NODE_COUNT) * Math.PI * 2;
    return {
      ...project(angle, 145, 116, "nodes"),
      tone: index % 3 === 0 ? "gold" : "blue",
      baseSize: index % 4 === 0 ? 4.15 : 3.15,
    };
  }).sort((left, right) => left.z - right.z);

  for (const node of nodes) {
    const depth = clamp((node.z + 130) / 260, 0, 1);
    const radius = node.baseSize * node.scale * (0.82 + depth * 0.38);
    const fill = node.tone === "gold"
      ? (paper ? "#c89024" : "#d5a940")
      : (paper ? "#1f6194" : "#315f9a");
    context.beginPath();
    context.arc(node.x, node.y, radius, 0, Math.PI * 2);
    context.fillStyle = fill;
    context.globalAlpha = 0.56 + depth * 0.44;
    context.fill();
    context.globalAlpha = 1;
    context.strokeStyle = border;
    context.lineWidth = 0.9 + depth * 0.5;
    context.stroke();
  }
}

function rgba(color: number[], alpha: number) {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}
