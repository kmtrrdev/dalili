// Interactive 3D globe.
//  - Idle (no destination yet): the Earth spins and live "air traffic" arcs criss-cross between world hubs.
//  - Journey set: traffic fades out, the Earth stops, the camera flies to frame the whole route
//    (origin -> stop 1 -> stop 2 -> ... -> home), and each leg draws in turn with a plane travelling it.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

const R = 100;
const DEG = Math.PI / 180;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function latLonToVec(lat, lon, r = R) {
  const phi = (90 - lat) * DEG;
  const theta = (lon + 180) * DEG;
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
}

function vecToLatLon(v) {
  const n = v.clone().normalize();
  return { lat: 90 - Math.acos(n.y) / DEG, lon: ((Math.atan2(n.z, -n.x) / DEG) - 180 + 540) % 360 - 180 };
}

// Major air hubs for the idle traffic animation (lat, lon).
const HUBS = [
  [51.47, -0.45], [40.64, -73.78], [25.25, 55.36], [35.55, 139.78], [1.36, 103.99], [49.01, 2.55], [30.12, 31.41],
  [-33.94, 151.18], [33.94, -118.41], [41.98, -87.9], [22.31, 113.92], [52.31, 4.76], [41.28, 28.75], [24.96, 46.7],
  [-23.43, -46.47], [19.09, 72.87], [37.46, 126.44], [-26.14, 28.24], [55.97, 37.41], [40.47, -3.56], [41.8, 12.25],
  [43.68, -79.63], [19.44, -99.07], [13.69, 100.75], [-34.82, -58.54], [50.04, 8.56], [25.07, 121.23], [6.58, 3.32],
];

const ATMOSPHERE_VERT = `
  varying vec3 vNormal;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const ATMOSPHERE_FRAG = `
  varying vec3 vNormal;
  uniform vec3 uColor;
  void main() {
    float intensity = pow(0.72 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.2);
    gl_FragColor = vec4(uColor, 1.0) * intensity;
  }`;
const ARC_VERT = `
  varying float vT;
  void main() {
    vT = uv.x;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const ARC_FRAG = `
  varying float vT;
  uniform float uTime;
  uniform float uReveal;
  uniform float uAlpha;
  uniform float uDash;
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  void main() {
    if (vT > uReveal) discard;
    float dash = step(0.45, fract(vT * uDash - uTime * 0.9));
    float head = smoothstep(uReveal - 0.08, uReveal, vT) * step(uReveal, 0.999);
    vec3 col = mix(uColorA, uColorB, vT) + head * 0.6;
    gl_FragColor = vec4(col, (0.35 + 0.65 * dash) * uAlpha);
  }`;
// Idle traffic: a short glowing comet travelling along the arc.
const TRAFFIC_FRAG = `
  varying float vT;
  uniform float uHead;
  uniform float uAlpha;
  uniform vec3 uColor;
  void main() {
    float d = uHead - vT;
    if (d < 0.0 || d > 0.28) discard;
    float a = pow(1.0 - d / 0.28, 2.0);
    gl_FragColor = vec4(uColor, a * uAlpha);
  }`;

const LEG_COLORS = [0xffb454, 0x3de0d0, 0x8b7bff, 0xff6fa3, 0x6fe38a, 0x4fb3ff, 0xffd166];

export class Globe {
  constructor(canvas, labelLayer) {
    this.canvas = canvas;
    this.labelLayer = labelLayer;
    this.markers = [];
    this.legs = [];         // {mesh, curve, plane, start}
    this.traffic = [];      // idle arcs
    this.trafficAlpha = 1;  // fades to 0 once a journey is locked
    this.locked = false;
    this.centerOffset = 0;
    this.flight = null;
    this.clock = new THREE.Clock();

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer = renderer;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 1, 3000);
    this.camera.position.set(0, 60, 330);

    const controls = new OrbitControls(this.camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 140;
    controls.maxDistance = 520;
    controls.rotateSpeed = 0.5;
    controls.autoRotate = !reduceMotion;
    controls.autoRotateSpeed = 0.35;
    // The wheel scrolls the page (the home page is scrollable over the globe); dragging spins the globe.
    controls.enableZoom = false;
    this.controls = controls;
    controls.addEventListener("start", () => { this.flight = null; });

    this._buildEarth();
    this._buildStars();
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.35));
    const sun = new THREE.DirectionalLight(0x9fd8ff, 1.2);
    sun.position.set(-300, 200, 300);
    this.scene.add(sun);
    this.trafficGroup = new THREE.Group();
    this.scene.add(this.trafficGroup);
    if (!reduceMotion) for (let i = 0; i < 9; i++) this._spawnTraffic(Math.random() * 4);

    this._resize = this._resize.bind(this);
    window.addEventListener("resize", this._resize);
    this._resize();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  _buildEarth() {
    const loader = new THREE.TextureLoader();
    this.loader = loader;
    const map = loader.load("/static/vendor/earth-night.jpg");
    map.colorSpace = THREE.SRGBColorSpace;
    map.anisotropy = 8;
    this.nightMap = map;
    const mat = new THREE.MeshPhongMaterial({
      map,
      bumpMap: loader.load("/static/vendor/earth-topology.png"),
      bumpScale: 1.2,
      specularMap: loader.load("/static/vendor/earth-water.png"),
      specular: new THREE.Color(0x2a4a6a),
      shininess: 18,
    });
    this.earth = new THREE.Mesh(new THREE.SphereGeometry(R, 96, 96), mat);
    this.scene.add(this.earth);

    const atmosphere = this.atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(R * 1.16, 64, 64),
      new THREE.ShaderMaterial({
        vertexShader: ATMOSPHERE_VERT, fragmentShader: ATMOSPHERE_FRAG,
        uniforms: { uColor: { value: new THREE.Color(0x3de0d0) } },
        blending: THREE.AdditiveBlending, side: THREE.BackSide, transparent: true, depthWrite: false,
      }),
    );
    this.scene.add(atmosphere);

    // Faint graticule gives the sphere a "planning instrument" feel.
    const grid = new THREE.Group();
    const gridMat = new THREE.LineBasicMaterial({ color: 0x3de0d0, transparent: true, opacity: 0.06 });
    for (let lat = -60; lat <= 60; lat += 30) {
      const pts = [];
      for (let lon = -180; lon <= 180; lon += 4) pts.push(latLonToVec(lat, lon, R * 1.003));
      grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
    }
    for (let lon = -180; lon < 180; lon += 30) {
      const pts = [];
      for (let lat = -90; lat <= 90; lat += 4) pts.push(latLonToVec(lat, lon, R * 1.003));
      grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
    }
    this.scene.add(grid);
  }

  _buildStars() {
    const n = 2600;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(900 + Math.random() * 500);
      pos.set([v.x, v.y, v.z], i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.stars = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xbfd6ff, size: 1.6, sizeAttenuation: true, transparent: true, opacity: 0.8 }));
    this.scene.add(this.stars);
  }

  _resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // Shift the globe so it sits in the free space between the chat and the trip board.
    this.camera.setViewOffset(w, h, -this.centerOffset, 0, w, h);
    this.camera.updateProjectionMatrix();
  }

  /** "dark": city lights at night + stars. "light": the daytime Earth under a soft blue atmosphere. */
  setTheme(theme) {
    const light = theme === "light";
    if (light && !this.dayMap) {
      this.dayMap = this.loader.load("/static/vendor/earth-day.jpg");
      this.dayMap.colorSpace = THREE.SRGBColorSpace;
      this.dayMap.anisotropy = 8;
    }
    const mat = this.earth.material;
    mat.map = light ? this.dayMap : this.nightMap;
    mat.shininess = light ? 10 : 18;
    mat.needsUpdate = true;
    this.atmosphere.material.uniforms.uColor.value.set(light ? 0x7cc4ff : 0x3de0d0);
    this.stars.visible = !light;
  }

  setCenterOffset(px) {
    this.centerOffset = px;
    this._resize();
  }

  // ------------------------------------------------------------------ idle traffic
  _spawnTraffic(delay = 0) {
    const a = HUBS[Math.floor(Math.random() * HUBS.length)];
    let b = HUBS[Math.floor(Math.random() * HUBS.length)];
    if (a === b) b = HUBS[(HUBS.indexOf(a) + 7) % HUBS.length];
    const curve = arcCurve({ lat: a[0], lon: a[1] }, { lat: b[0], lon: b[1] }, 0.8);
    const mat = new THREE.ShaderMaterial({
      vertexShader: ARC_VERT, fragmentShader: TRAFFIC_FRAG, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: { uHead: { value: -delay }, uAlpha: { value: 0 }, uColor: { value: new THREE.Color(Math.random() < 0.5 ? 0x3de0d0 : 0x8fb8ff) } },
    });
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 90, 0.35, 6, false), mat);
    this.trafficGroup.add(mesh);
    this.traffic.push({ mesh, speed: 0.16 + Math.random() * 0.12 });
  }

  _updateTraffic(dt) {
    this.trafficAlpha = this.locked ? Math.max(0, this.trafficAlpha - dt * 1.2) : Math.min(1, this.trafficAlpha + dt * 0.8);
    this.trafficGroup.visible = this.trafficAlpha > 0.01;
    if (!this.trafficGroup.visible) return;
    for (const tr of [...this.traffic]) {
      const u = tr.mesh.material.uniforms;
      u.uHead.value += dt * tr.speed;
      u.uAlpha.value = 0.75 * this.trafficAlpha;
      if (u.uHead.value > 1.3) {
        this.trafficGroup.remove(tr.mesh);
        tr.mesh.geometry.dispose();
        tr.mesh.material.dispose();
        this.traffic.splice(this.traffic.indexOf(tr), 1);
        if (!this.locked) this._spawnTraffic(Math.random() * 1.5);
      }
    }
  }

  // ------------------------------------------------------------------ markers + journey
  clearRoute() {
    for (const m of this.markers) {
      this.scene.remove(m.group);
      m.label.remove();
    }
    this.markers = [];
    for (const leg of this.legs) {
      this.scene.remove(leg.mesh);
      if (leg.plane) this.scene.remove(leg.plane);
    }
    this.legs = [];
    this.journeyStart = null;
    // Back to idle: spin again, free to drag, and bring the traffic back.
    if (this.locked) {
      this.locked = false;
      this.controls.autoRotate = !reduceMotion;
      this.controls.enableRotate = true;
      this.canvas.classList.remove("locked");
      if (!reduceMotion) while (this.traffic.length < 9) this._spawnTraffic(Math.random() * 2);
    }
  }

  addMarker(lat, lon, label, color = 0x3de0d0, kind = "dest", badge = "") {
    // The group sits on the surface, so scaling it grows / shrinks the marker in place.
    const group = new THREE.Group();
    const pos = latLonToVec(lat, lon, R * 1.005);
    const normal = pos.clone().normalize();
    group.position.copy(pos);
    group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);  // local +z = up from the ground
    const dot = new THREE.Mesh(new THREE.SphereGeometry(kind === "origin" ? 1.5 : 1.3, 16, 16), new THREE.MeshBasicMaterial({ color }));
    group.add(dot);
    const ringMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false });
    const ring = new THREE.Mesh(new THREE.RingGeometry(2.0, 2.6, 40), ringMat);
    group.add(ring);
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.22, 0.22, 12, 8),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55 }),
    );
    beam.rotation.x = Math.PI / 2;  // cylinder axis (y) -> local z
    beam.position.z = 6;
    group.add(beam);
    group.scale.setScalar(reduceMotion ? 1 : 0.001);
    this.scene.add(group);

    const el = document.createElement("div");
    el.className = `globe-label ${kind}`;
    if (badge) {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = badge;
      el.appendChild(b);
    }
    el.appendChild(document.createTextNode(label));
    el.style.setProperty("--c", `#${new THREE.Color(color).getHexString()}`);
    this.labelLayer.appendChild(el);
    this.markers.push({ group, ring, pos, label: el, phase: Math.random() * Math.PI, born: performance.now() });
  }

  // Backwards-compatible single destination.
  setRoute(origin, dest) {
    this.setJourney(origin, dest ? [dest] : []);
  }

  /**
   * origin: {lat, lon, name} | null; stops: [{lat, lon, name}] in visit order.
   * Draws origin -> stop 1 -> ... -> stop n -> origin and frames all of it.
   */
  setJourney(origin, stops) {
    this.clearRoute();
    stops = (stops || []).filter(Boolean);
    if (!stops.length && !origin) return;
    if (origin) this.addMarker(origin.lat, origin.lon, origin.name, 0xffb454, "origin", "⌂");
    stops.forEach((s, i) => {
      const color = stops.length > 1 ? LEG_COLORS[(i + 1) % LEG_COLORS.length] : 0x3de0d0;
      this.addMarker(s.lat, s.lon, s.name, color, "dest", stops.length > 1 ? String(i + 1) : "");
    });
    if (!stops.length) return;

    const chain = origin ? [origin, ...stops, origin] : stops;
    const n = chain.length - 1;
    for (let i = 0; i < n; i++) {
      const a = chain[i], b = chain[i + 1];
      const home = origin && i === n - 1 && stops.length > 0;
      const colorA = new THREE.Color(i === 0 && origin ? 0xffb454 : LEG_COLORS[i % LEG_COLORS.length]);
      const colorB = new THREE.Color(home ? 0xffb454 : (stops.length > 1 ? LEG_COLORS[(i + 1) % LEG_COLORS.length] : 0x3de0d0));
      const curve = arcCurve(a, b, 0.5);
      const mat = new THREE.ShaderMaterial({
        vertexShader: ARC_VERT, fragmentShader: ARC_FRAG, transparent: true, depthWrite: false,
        uniforms: {
          uTime: { value: 0 }, uReveal: { value: reduceMotion ? 1 : 0 }, uAlpha: { value: home ? 0.45 : 1 },
          uDash: { value: home ? 34 : 22 }, uColorA: { value: colorA }, uColorB: { value: colorB },
        },
      });
      const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 160, home ? 0.35 : 0.55, 8, false), mat);
      this.scene.add(mesh);
      const plane = new THREE.Mesh(new THREE.SphereGeometry(1.2, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      plane.add(new THREE.Mesh(new THREE.SphereGeometry(2.8, 16, 16),
        new THREE.MeshBasicMaterial({ color: colorB, transparent: true, opacity: 0.3, depthWrite: false })));
      plane.visible = false;
      this.scene.add(plane);
      this.legs.push({ mesh, curve, plane, start: 0.45 + i * 0.75, home });
    }
    this.journeyStart = this.clock.elapsedTime;
    this.lockOn([...(origin ? [origin] : []), ...stops]);
  }

  /** Free screen area the route must fit in (e.g. between the chat and the board), in px from the left. */
  setSafeArea(left, right) {
    const prev = this.safe || [0, 0];
    this.safe = [left, right];
    const changed = Math.abs(prev[0] - left) > 20 || Math.abs(prev[1] - right) > 20;
    if (changed && this.locked && this._lockPoints) this.lockOn(this._lockPoints, true);
  }

  /** Stop spinning and turn the globe so every point and arc sits in the free space (camera distance unchanged). */
  lockOn(points, quick = false) {
    this.locked = true;
    this._lockPoints = points;
    this.controls.autoRotate = false;
    this.controls.enableRotate = false;  // the route stays in view: no dragging once a trip is on the globe
    this.canvas.classList.add("locked");
    clearTimeout(this._resume);
    const vecs = points.map((p) => latLonToVec(p.lat, p.lon).normalize());
    const centre = vecs.reduce((acc, v) => acc.add(v), new THREE.Vector3());
    if (centre.lengthSq() < 1e-6) centre.copy(vecs[0]);
    centre.normalize();
    // Everything that must stay visible: the places and the top of every arc.
    const fit = [...vecs.map((v) => v.clone().multiplyScalar(R * 1.01)), ...this.legs.map((l) => l.curve.getPointAt(0.5))];
    const w = window.innerWidth, h = window.innerHeight;
    const [left, right] = this.safe || [w * 0.1, w * 0.9];
    // Labels sit to the right of their point, so the right edge needs more room than the left.
    const minX = left + 20, maxX = Math.max(left + 120, right - 120);
    const minY = 130, maxY = h - 80;
    const probe = this.camera.clone();
    const pxPerRad = (h / 2) / Math.tan((probe.fov / 2) * DEG);
    // At distance d, aim so the route's screen bounding box is centred in the free box; null if it can't fit.
    const aimAt = (d) => {
      const dir = centre.clone();
      for (let it = 0; it < 5; it++) {
        probe.position.copy(dir).multiplyScalar(d);
        probe.up.set(0, 1, 0);
        probe.lookAt(0, 0, 0);
        probe.updateMatrixWorld(true);
        let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
        for (const p of fit) {
          const s = p.clone().project(probe);
          if (s.z >= 1) return null;
          const x = ((s.x + 1) / 2) * w, y = ((1 - s.y) / 2) * h;
          x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
        }
        const ex = (x0 + x1) / 2 - (minX + maxX) / 2, ey = (y0 + y1) / 2 - (minY + maxY) / 2;
        if (Math.abs(ex) < 3 && Math.abs(ey) < 3) break;
        const gain = pxPerRad * R / Math.max(d - R, 1);
        const right = new THREE.Vector3(1, 0, 0).applyQuaternion(probe.quaternion);
        const up = new THREE.Vector3(0, 1, 0).applyQuaternion(probe.quaternion);
        dir.addScaledVector(right, ex / gain).addScaledVector(up, -ey / gain).normalize();
      }
      return dir;
    };
    // No zoom: keep the normal viewing distance, only turn the globe so the route sits in the free space.
    const distance = this.camera.position.length();
    const aim = aimAt(distance) || centre;
    const target = vecToLatLon(aim);
    if (quick && this.flight) {
      // Layout changed mid-flight (the board just opened): retarget the same smooth flight.
      this.flight.to = latLonToVec(target.lat, target.lon).normalize().multiplyScalar(distance);
      return;
    }
    this.focus(target, distance, true);
  }

  focus(point, distance = 260, stay = false) {
    const target = latLonToVec(point.lat, point.lon).normalize().multiplyScalar(distance);
    if (reduceMotion) {
      this.camera.position.copy(target);
      return;
    }
    this.controls.autoRotate = false;
    this.flight = { from: this.camera.position.clone(), to: target, t: 0 };
    clearTimeout(this._resume);
    if (!stay && !this.locked) this._resume = setTimeout(() => { this.controls.autoRotate = !reduceMotion; }, 9000);
  }

  pulse() {
    // A quick "working" signal while the agent researches.
    this.pulseUntil = performance.now() + 1200;
  }

  _loop() {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    const t = this.clock.elapsedTime;
    if (this.flight) {
      this.flight.t = Math.min(1, this.flight.t + dt / 2.2);
      const e = easeInOut(this.flight.t);
      const from = this.flight.from.clone().normalize();
      const to = this.flight.to.clone().normalize();
      const len = THREE.MathUtils.lerp(this.flight.from.length(), this.flight.to.length(), e);
      this.camera.position.copy(slerp(from, to, e).multiplyScalar(len));
      if (this.flight.t >= 1) this.flight = null;
    }
    this.controls.update();
    this.stars.rotation.y += dt * 0.004;
    this._updateTraffic(dt);

    // Journey legs draw one after another; then a plane loops over the whole route.
    const since = this.journeyStart == null ? 0 : t - this.journeyStart;
    const cycle = this.legs.length * 2.6;
    this.legs.forEach((leg, i) => {
      const u = leg.mesh.material.uniforms;
      u.uTime.value = t;
      if (!reduceMotion) u.uReveal.value = THREE.MathUtils.clamp((since - leg.start) / 0.9, 0, 1);
      const local = ((since - this.legs.length * 0.75 - 0.6) % cycle) / 2.6 - i;
      const on = u.uReveal.value >= 1 && local >= 0 && local < 1;
      leg.plane.visible = on;
      if (on) leg.plane.position.copy(leg.curve.getPointAt(easeInOut(local)));
    });

    const pulsing = this.pulseUntil && performance.now() < this.pulseUntil;
    const camDir = this.camera.position.clone().normalize();
    const w = window.innerWidth, h = window.innerHeight;
    const now = performance.now();
    // Markers keep a similar on-screen size when the camera zooms in on a region.
    const k = THREE.MathUtils.clamp(this.camera.position.length() / 330, 0.4, 1.1);
    for (const leg of this.legs) leg.plane.scale.setScalar(k);
    for (const m of this.markers) {
      const grow = Math.min(1, (now - m.born) / 650);
      m.group.scale.setScalar((reduceMotion ? 1 : easeOutBack(grow)) * k);
      const s = 1 + ((Math.sin(t * (pulsing ? 6 : 2.4) + m.phase) + 1) / 2) * 1.6;
      m.ring.scale.set(s, s, s);
      m.ring.material.opacity = 0.9 - (s - 1) / 2.2;
      const facing = m.pos.clone().normalize().dot(camDir);
      const sp = m.pos.clone().project(this.camera);
      m.sx = ((sp.x + 1) / 2) * w;
      m.sy = ((1 - sp.y) / 2) * h;
      m.visible = facing > 0.15 && grow > 0.5;
    }
    // Nearby cities: stack their labels instead of drawing them on top of each other.
    const placed = [];
    for (const m of this.markers) {
      let y = m.sy;
      const lw = m.label.offsetWidth || 90;
      for (let tries = 0; tries < 6; tries++) {
        const hit = placed.find((p) => m.sx < p.x + p.w && p.x < m.sx + lw && Math.abs(y - p.y) < 26);
        if (!hit) break;
        y = hit.y + (y >= hit.y ? 27 : -27);
      }
      if (m.visible) placed.push({ x: m.sx, y, w: lw });
      m.label.style.transform = `translate(${m.sx}px, ${y}px)`;
      m.label.style.opacity = m.visible ? "1" : "0";
    }
    this.renderer.render(this.scene, this.camera);
    requestAnimationFrame(this._loop);
  }
}

function arcCurve(a, b, liftScale = 1) {
  const va = latLonToVec(a.lat, a.lon).normalize();
  const vb = latLonToVec(b.lat, b.lon).normalize();
  const angle = va.angleTo(vb);
  const lift = (3 + angle * 45) * liftScale;
  const pts = [];
  for (let i = 0; i <= 100; i++) {
    const t = i / 100;
    pts.push(slerp(va, vb, t).multiplyScalar(R + 0.8 + Math.sin(Math.PI * t) * lift));
  }
  return new THREE.CatmullRomCurve3(pts);
}

function slerp(a, b, t) {
  const angle = a.angleTo(b);
  if (angle < 1e-6) return a.clone();
  const s = Math.sin(angle);
  return a.clone().multiplyScalar(Math.sin((1 - t) * angle) / s).add(b.clone().multiplyScalar(Math.sin(t * angle) / s));
}

function easeInOut(x) {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

function easeOutBack(x) {
  const c1 = 1.70158, c3 = c1 + 1;
  return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
}
