const byId = (id) => document.getElementById(id);
const capture = JSON.parse(byId('capture-data').textContent);
const fit = JSON.parse(byId('fit-data').textContent);
const { frames, voxelMM } = capture;
const front = frames.findIndex((frame) => frame.angle === 0);
const angle = byId('angle');
const canvas = byId('cloud');
const context = canvas.getContext('2d');
const collected = new Set();
const cloud = new Map();
let selected = front;
let azimuth = 0.45;
let elevation = 0.23;
let distance = 0.85;
let timer = null;
let paintPending = false;

const bearing = (degrees) => ((degrees % 360) + 360) % 360 + '°';
angle.min = 0;
angle.max = frames.length - 1;
byId('map').innerHTML = '<span class="target">R7</span><span class="map-label rear">背面</span><span class="map-label front">正面</span>';
const stations = frames.map((frame, index) => {
  const marker = document.createElement('button');
  const r = frame.angle * Math.PI / 180;
  marker.type = 'button';
  marker.className = 'station';
  marker.style.left = 50 + 35 * Math.sin(r) + '%';
  marker.style.top = 50 + 35 * Math.cos(r) + '%';
  marker.title = '机位 ' + bearing(frame.angle);
  marker.setAttribute('aria-label', marker.title);
  marker.addEventListener('click', () => { stopSweep(); select(index); });
  byId('map').append(marker);
  return marker;
});

function select(index) {
  selected = index;
  angle.value = index;
  const frame = frames[index];
  byId('bearing').value = bearing(frame.angle);
  angle.setAttribute('aria-valuetext', bearing(frame.angle));
  byId('rgb').src = frame.rgb;
  byId('depth').src = frame.depth;
  byId('depth-limits').textContent = '表面 ' + (frame.min / 1000).toFixed(2) + '–' + (frame.max / 1000).toFixed(2) + ' m';
  stations.forEach((marker, i) => marker.setAttribute('aria-current', String(index === i)));
  updateCounts();
}

function updateCounts() {
  byId('counter').value = collected.size + ' / ' + frames.length + ' 机位';
  byId('point-count').value = cloud.size.toLocaleString('zh-CN') + ' 点';
  byId('shot').disabled = timer !== null || collected.has(selected);
  byId('shot').textContent = collected.has(selected) ? '当前帧已采集' : '采集当前帧';
}

function takeShot(index) {
  if (collected.has(index)) return;
  const raw = Uint8Array.from(atob(frames[index].samples), (value) => value.charCodeAt(0));
  const points = new DataView(raw.buffer);
  for (let at = 0; at < points.byteLength; at += 12) {
    const x = points.getInt16(at, true);
    const y = points.getInt16(at + 2, true);
    const z = points.getInt16(at + 4, true);
    const key = [x, y, z].map((axis) => Math.floor(axis / voxelMM)).join(',');
    if (!cloud.has(key)) {
      const rgb = [6, 8, 10].map((offset) => points.getInt16(at + offset, true));
      cloud.set(key, [x / 1000, y / 1000, z / 1000, 'rgb(' + rgb.join(',') + ')']);
    }
  }
  collected.add(index);
  stations[index].classList.add('collected');
  updateCounts();
  schedulePaint();
}

function stopSweep() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  byId('sweep').textContent = '开始一圈补拍';
  updateCounts();
}

function startSweep() {
  let step = 0;
  function tick() {
    const index = (front + step) % frames.length;
    select(index);
    takeShot(index);
    step++;
    if (step < frames.length) timer = setTimeout(tick, 95);
    else stopSweep();
  }
  byId('sweep').textContent = '暂停补拍';
  timer = setTimeout(tick, 0);
}

function setView(yaw) {
  azimuth = yaw;
  elevation = 0.23;
  distance = 0.85;
  schedulePaint();
}

function drawCloud() {
  paintPending = false;
  const { width, height } = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const bufferWidth = Math.round(width * pixelRatio);
  const bufferHeight = Math.round(height * pixelRatio);
  if (canvas.width !== bufferWidth) canvas.width = bufferWidth;
  if (canvas.height !== bufferHeight) canvas.height = bufferHeight;
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  const cosA = Math.cos(azimuth), sinA = Math.sin(azimuth);
  const cosE = Math.cos(elevation), sinE = Math.sin(elevation);
  const focal = Math.min(width, height) * 1.24;
  function project(x, y, z) {
    const lateral = x * cosA - z * sinA;
    const radial = z * cosA + x * sinA;
    const vertical = y - capture.targetY;
    const depth = distance - radial * cosE - vertical * sinE;
    const up = vertical * cosE - radial * sinE;
    return [width / 2 + focal * lateral / depth, height * 0.45 - focal * up / depth, depth];
  }

  context.strokeStyle = '#63877640';
  context.lineWidth = 1;
  for (let lane = -4; lane <= 4; lane++) {
    const v = lane / 10;
    const lines = [[project(v, 0, -.4), project(v, 0, .4)],
                   [project(-.4, 0, v), project(.4, 0, v)]];
    for (const [start, end] of lines) {
      context.beginPath();
      context.moveTo(start[0], start[1]);
      context.lineTo(end[0], end[1]);
      context.stroke();
    }
  }

  const visible = [];
  for (const [x, y, z, color] of cloud.values()) {
    const point = project(x, y, z);
    if (point[2] > 0.07) visible.push([...point, color]);
  }
  visible.sort((a, b) => b[2] - a[2]);
  for (const [x, y, z, color] of visible) {
    const size = Math.max(1.3, Math.min(4.5, focal * .0048 / z));
    context.fillStyle = color;
    context.fillRect(x - size / 2, y - size / 2, size, size);
  }
}

function schedulePaint() {
  if (paintPending) return;
  paintPending = true;
  requestAnimationFrame(drawCloud);
}

let drag = null;
canvas.addEventListener('pointerdown', (event) => {
  if (!event.isPrimary || event.button !== 0) return;
  canvas.setPointerCapture(event.pointerId);
  drag = [event.clientX, event.clientY];
});
canvas.addEventListener('pointermove', (event) => {
  if (!drag || !event.isPrimary) return;
  azimuth -= (event.clientX - drag[0]) * .012;
  elevation = Math.max(-1.2, Math.min(1.2, elevation + (event.clientY - drag[1]) * .010));
  drag = [event.clientX, event.clientY];
  schedulePaint();
});
canvas.addEventListener('lostpointercapture', () => { drag = null; });
canvas.addEventListener('wheel', (event) => {
  event.preventDefault();
  distance = Math.max(.64, Math.min(1.75, distance * Math.exp(event.deltaY * .001)));
  schedulePaint();
}, { passive: false });
canvas.addEventListener('keydown', (event) => {
  const rotations = { ArrowLeft: [-.12, 0], ArrowRight: [.12, 0], ArrowUp: [0, .1], ArrowDown: [0, -.1] };
  if (!Object.hasOwn(rotations, event.key)) return;
  event.preventDefault();
  const [yaw, pitch] = rotations[event.key];
  azimuth += yaw;
  elevation = Math.max(-1.2, Math.min(1.2, elevation + pitch));
  schedulePaint();
});

byId('point-front').addEventListener('click', () => setView(0));
byId('point-back').addEventListener('click', () => setView(Math.PI));
new ResizeObserver(schedulePaint).observe(canvas);
angle.addEventListener('input', () => { stopSweep(); select(Number(angle.value)); });
byId('shot').addEventListener('click', () => takeShot(selected));
byId('reset').addEventListener('click', () => {
  stopSweep();
  cloud.clear();
  collected.clear();
  stations.forEach((marker) => marker.classList.remove('collected'));
  select(front);
  takeShot(front);
  setView(.45);
});
byId('sweep').addEventListener('click', () => { if (timer === null) startSweep(); else stopSweep(); });

byId('heldout').src = fit.reference;
byId('depth-limits').nextElementSibling.title = '颜色范围 ' + capture.depthLimits.join('–') + ' m';
byId('heldout-angle').textContent = bearing(capture.holdoutAngle);
byId('fit-front').src = fit.front;
byId('fit-full').src = fit.full;
byId('front-count').textContent = capture.frontCount + ' 张';
byId('full-count').textContent = frames.length + ' 张';
select(front);
takeShot(front);
