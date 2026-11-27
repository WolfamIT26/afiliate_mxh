(() => {
  'use strict';

  const WIDTH = 1000;
  const BOTTOM = 616;
  const REAR = -125;
  const DEGREE = Math.PI / 180;
  const DARK = '#071d24';
  const COLD = {
    upper: '#377a79', lower: '#164b54', side: '#235b61', floor: '#80a5a1',
    light: '#7dffe3', tint: '#58c9ba', trim: '#387a7f', desk: '#c8b89d',
  };
  const WARM = {
    upper: '#a46732', lower: '#483321', side: '#7b542f', floor: '#d39b61',
    light: '#ffe4a2', tint: '#fbbb6b', trim: '#a57340', desk: '#f1c293',
  };
  const TEAL = {
    upper: '#229187', lower: '#104655', side: '#286771', floor: '#6f9e9d',
    light: '#77ffe6', tint: '#32d5c8', trim: '#3e8b81', desk: '#d1bc8b',
  };
  const DEPARTMENTS = Array.from({length: 20}, (_, index) => ({
    index,
    left: index % 5 * 200,
    right: (index % 5 + 1) * 200,
    top: 170 + Math.floor(index / 5) * 111,
    bottom: 283 + Math.floor(index / 5) * 111,
  }));
  const OWNER = {index: 20, left: 0, right: 285, top: 55, bottom: 170};
  const ORCHESTRATOR = {index: 21, left: 285, right: 740, top: 55, bottom: 170};
  const LOUNGE = {index: 22, left: 740, right: 1000, top: 55, bottom: 170};
  const ROOMS = [OWNER, ORCHESTRATOR, LOUNGE, ...DEPARTMENTS];

  function createOfficeScene(canvas, {onPositions = () => {}} = {}) {
    const context = canvas.getContext('2d', {alpha: true});
    const base = document.createElement('canvas');
    const overlay = document.createElement('canvas');
    const baseContext = base.getContext('2d', {alpha: true});
    const overlayContext = overlay.getContext('2d', {alpha: true});
    let brush = context;
    let width = 0;
    let height = 0;
    let scale = 1;
    let pixelRatio = 1;
    let yaw = -5;
    let pitch = 3;
    let zoom = 1;
    let sinYaw = 0;
    let cosYaw = 1;
    let sinPitch = 0;
    let cosPitch = 1;
    let motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let activeRooms = new Set();
    let selected = -1;
    let timer = 0;
    let lastFrame = 0;
    let sceneTime = 0;
    let resizeObserver;
    let destroyed = false;

    function project(x, y, z) {
      const dx = x - WIDTH / 2;
      const dy = y - 304;
      const rotatedX = dx * cosYaw + z * sinYaw;
      const aroundY = -dx * sinYaw + z * cosYaw;
      const rotatedY = dy * cosPitch + aroundY * sinPitch;
      const depth = aroundY * cosPitch - dy * sinPitch;
      const size = scale * (1 + depth / 2900);
      return {
        x: width / 2 + rotatedX * size,
        y: height / 2 + rotatedY * size,
        size,
      };
    }

    function facet(points, paint) {
      brush.beginPath();
      points.forEach(([x, y, z], index) => {
        const point = project(x, y, z);
        if (index === 0) brush.moveTo(point.x, point.y);
        else brush.lineTo(point.x, point.y);
      });
      brush.closePath();
      brush.fillStyle = paint;
      brush.fill();
    }

    function edge(points, color, thickness = 1) {
      brush.beginPath();
      points.forEach(([x, y, z], index) => {
        const point = project(x, y, z);
        if (index === 0) brush.moveTo(point.x, point.y);
        else brush.lineTo(point.x, point.y);
      });
      brush.strokeStyle = color;
      brush.lineWidth = Math.max(.45, thickness * scale);
      brush.lineCap = 'round';
      brush.lineJoin = 'round';
      brush.stroke();
    }

    function box(x, y, z, w, h, depth, front, top, side) {
      const r = x + w;
      const b = y + h;
      const f = z + depth;
      facet([[x, y, z], [r, y, z], [r, y, f], [x, y, f]], top);
      if (sinYaw < 0) facet([[x, y, z], [x, y, f], [x, b, f], [x, b, z]], side);
      else facet([[r, y, z], [r, y, f], [r, b, f], [r, b, z]], side);
      facet([[x, y, f], [r, y, f], [r, b, f], [x, b, f]], front);
    }

    function glow(x, y, z, rx, ry, color, power = .48) {
      const point = project(x, y, z);
      brush.save();
      brush.translate(point.x, point.y);
      brush.scale(rx * point.size, ry * point.size);
      const gradient = brush.createRadialGradient(0, 0, 0, 0, 0, 1);
      gradient.addColorStop(0, color);
      gradient.addColorStop(1, 'transparent');
      brush.globalAlpha = power;
      brush.fillStyle = gradient;
      brush.fillRect(-1, -1, 2, 2);
      brush.restore();
    }

    function roundShape(x, y, w, h, radius, paint) {
      brush.beginPath();
      brush.roundRect(x, y, w, h, radius);
      brush.fillStyle = paint;
      brush.fill();
    }

    function circle(x, y, rx, ry, paint, angle = 0) {
      brush.beginPath();
      brush.ellipse(x, y, rx, ry, angle, 0, Math.PI * 2);
      brush.fillStyle = paint;
      brush.fill();
    }

    function localAt(x, y, z, render) {
      const point = project(x, y, z);
      brush.save();
      brush.translate(point.x, point.y);
      brush.scale(point.size, point.size);
      render();
      brush.restore();
    }

    function plant(x, y, z, seed, heightScale = 1) {
      glow(x, y - 2, z, 19 * heightScale, 6, '#071e23', .58);
      localAt(x, y, z, () => {
        brush.scale(heightScale, heightScale);
        const pot = brush.createLinearGradient(-7, 0, 8, 0);
        pot.addColorStop(0, '#a9a296');
        pot.addColorStop(.38, '#efe8d6');
        pot.addColorStop(1, '#878c80');
        roundShape(-7, -14, 14, 14, [2, 2, 4, 4], pot);
        circle(0, -14, 7, 2, '#665d47');
        brush.strokeStyle = '#638155';
        brush.lineWidth = 1;
        for (let branch = 0; branch < 8; branch += 1) {
          const phase = branch * 1.73 + seed;
          const px = Math.cos(phase) * (8 + branch % 4);
          const py = -25 - Math.sin(branch * 1.17 + seed) * 11;
          brush.beginPath();
          brush.moveTo(0, -13);
          brush.lineTo(px, py);
          brush.stroke();
          circle(px, py, 5.4, 2.4, ['#8bb94a', '#4d922e', '#346735', '#b2c965'][branch % 4], phase);
        }
      });
    }

    function shelf(x, y, z, wide = 31) {
      box(x, y, z, wide, 54, 13, '#8c693f', '#dcb979', '#634d36');
      for (let row = 0; row < 3; row += 1) {
        const yBook = y + 4 + row * 16;
        box(x + 2, yBook, z + 1, wide - 4, 13, 12, '#483b2c', '#bc8b56', '#483b2c');
        for (let index = 0; index < 7; index += 1) {
          const bar = ['#bda75d', '#dbd1ab', '#699a94', '#866537', '#ab6c45'][index % 5];
          const h = 7 + ((index * 7 + row * 3) % 5);
          box(x + 4 + index * (wide - 8) / 7, yBook + 12 - h, z + 10, 2.3, h, 4, bar, '#dec98f', '#655b47');
        }
      }
    }

    function server(x, y, z) {
      box(x, y, z, 27, 52, 16, '#1b3038', '#3d575d', '#14262e');
      for (let i = 0; i < 7; i += 1) {
        const yy = y + 4 + i * 6.7;
        box(x + 3, yy, z + 16, 21, 4, .8, i % 2 ? '#1e414f' : '#20363f', '#476c73', '#1d3137');
        edge([[x+7, yy+2, z+17], [x+12, yy+2, z+17]], '#66d9f5', .7);
        edge([[x+18, yy+2, z+17], [x+20, yy+2, z+17]], '#85c773', .7);
      }
    }

    function dashboard(x, y, z, w, h, style, tint) {
      box(x, y, z, w, h, 3, '#0b3441', '#63aab0', '#244a52');
      const front = z + 4;
      edge([[x+3, y+2, front],[x+w-3, y+2, front]], tint, .65);
      if (style % 3 === 0) {
        for (let bar = 0; bar < 6; bar += 1) {
          const tall = (4 + ((bar + 1) * (style % 2 + 2)) % 13 + bar) * h / 28;
          const bx = x + w * (.12 + bar * .12);
          box(bx, y + h - 5 - tall, front, w * .072, tall, .3, bar % 2 ? '#68dacc' : '#468a94', '#9bffee', '#376f77');
        }
      } else if (style % 3 === 1) {
        const points = [1, 4, 3, 7, 5, 10, 8].map((n, i) => [x + w * (.09 + i * .135), y + h * (.77 - n * .053), front]);
        for (const fraction of [.27, .5, .73]) {
          edge([[x+4, y+h*fraction, front], [x+w-4, y+h*fraction, front]], '#275562', .55);
        }
        edge(points, tint, 1.25);
      } else {
        localAt(x + w * .48, y + h * .56, front, () => {
          brush.lineWidth = h * .13;
          brush.strokeStyle = '#235762';
          brush.beginPath();
          brush.arc(0, 0, h * .28, 0, Math.PI * 2);
          brush.stroke();
          brush.strokeStyle = tint;
          brush.beginPath();
          brush.arc(0, 0, h * .28, -Math.PI / 2, Math.PI * .77);
          brush.stroke();
        });
      }
    }

    function chair(x, y, z, color = '#27434a') {
      box(x - 12, y - 30, z - 9, 24, 22, 5, color, '#577275', '#142f38');
      box(x - 11, y - 8, z - 8, 22, 5, 15, color, '#557279', '#18363d');
      box(x - 2, y - 2, z, 4, 9, 5, '#30464b', '#8b9b97', '#21343a');
    }

    function table(x, y, z, w, theme, long = false) {
      glow(x + w * .5, y + 20, z + 6, w * .62, 8, '#122326', .49);
      box(x + 4, y, z + 4, 4, 24, 4, '#776b59', '#c1b89f', '#403c38');
      box(x + w - 9, y, z + 4, 4, 24, 4, '#736956', '#bcab8d', '#524739');
      box(x - 1, y - 4, z - 10, w + 2, 5, 23, '#a59275', theme.desk, '#807059');
      edge([[x, y - 3.9, z + 13.5], [x+w, y - 3.9, z + 13.5]], '#f6e3bf', .7);
      if (long) box(x + w * .12, y + 1, z + 10, w * .76, 13, 2, '#756753', '#d1bf9d', '#776653');
    }

    function laptop(x, y, z, accent, large = false) {
      const w = large ? 23 : 17;
      const h = large ? 14 : 10;
      box(x, y - 2, z - 6, w + 6, 2, 13, '#2d444a', '#718982', '#263c45');
      facet([[x + 2, y - 2, z + 1], [x + w + 2, y - 2, z + 1],
        [x + w + 1, y - h, z - 3], [x + 1, y - h, z - 3]], '#183c49');
      edge([[x + 4, y - h + 3, z - 2], [x + w - 3, y - h + 3, z - 2]], accent, .8);
      edge([[x + 4, y - h + 6, z - 1], [x + w - 7, y - h + 6, z - 1]], '#6b9da0', .65);
    }

    function sofa(x, y, z, w) {
      box(x, y - 20, z, w, 17, 9, '#586765', '#9caaa2', '#243b40');
      box(x, y - 9, z + 9, w, 8, 14, '#576565', '#85928a', '#31474b');
      for (const left of [x - 4, x + w - 1]) {
        box(left, y - 14, z + 5, 6, 13, 18, '#748380', '#b3beb2', '#405653');
      }
      box(x + 5, y - 1, z + 14, w - 10, 5, 4, '#283d42', '#798880', '#25343a');
    }

    function roomTheme(room) {
      if (room.index === ORCHESTRATOR.index) return TEAL;
      if (activeRooms.has(room.index)) return WARM;
      return COLD;
    }

    function drawDepth(room) {
      const {left: x, right: r, top: t, bottom: b, index} = room;
      const colors = roomTheme(room);
      const top = project(x, t, REAR);
      const bottom = project(x, b, REAR);
      const wall = brush.createLinearGradient(top.x, top.y, bottom.x, bottom.y);
      wall.addColorStop(0, colors.upper);
      wall.addColorStop(.55, colors.lower);
      wall.addColorStop(1, '#1a3b3b');
      facet([[x, t, REAR], [r, t, REAR], [r, b, REAR], [x, b, REAR]], wall);
      facet([[x, t, REAR], [x, t, 2], [x, b, 2], [x, b, REAR]], colors.side);
      facet([[r, t, REAR], [r, t, 2], [r, b, 2], [r, b, REAR]], colors.side);
      facet([[x, b, REAR], [r, b, REAR], [r, b, 10], [x, b, 10]], colors.floor);
      facet([[x, t, REAR], [r, t, REAR], [r, t, 7], [x, t, 7]], '#354f52');
      facet([[x, b, REAR], [r, b, REAR], [r, b - 5, REAR], [x, b - 5, REAR]], '#446263');
      for (let shift = 27; shift < r - x; shift += 37) {
        edge([[x+shift, b, REAR], [x+shift, b, 9]], 'rgba(18, 48, 53, .19)', .7);
      }
      for (const z of [-84, -49, -17]) {
        edge([[x, b, z], [r, b, z]], 'rgba(26, 61, 66, .17)', .65);
      }
      for (let step = 1; step < 6; step += 1) {
        const divider = x + (r - x) * step / 6;
        edge([[divider, t + 2, REAR + .2], [divider, b - 6, REAR + .2]], 'rgba(174, 225, 213, .13)', .7);
      }
      const center = (x + r) / 2;
      edge([[x+10, t+3, -83], [r-10, t+3, -83]], colors.light, 1.8);
      edge([[x+14, t+3, -9], [r-14, t+3, -9]], '#f2e1b9', 1.05);
      glow(center, t + 18, REAR + 2, (r - x) * .36, 34, colors.tint, .48);
      glow(center, b - 4, -40, (r - x) * .37, 11, colors.light, .42);

      if (index === ORCHESTRATOR.index) {
        for (let i = 0; i < 3; i += 1) dashboard(center - 142 + i * 100, t + 35, -117, 82, 41, i, colors.light);
        plant(x + 24, b - 2, -52, 7, 1.22);
        plant(r - 24, b - 2, -52, 8, 1.22);
      } else if (index === OWNER.index || index === LOUNGE.index) {
        shelf(x + 20, b - 60, -106, 35);
        plant(r - 24, b - 4, -41, index, 1.2);
        if (index === LOUNGE.index) {
          sofa(center - 47, b - 14, -65, 94);
          sofa(r - 55, b - 20, -59, 27);
          table(center - 23, b - 25, -30, 46, colors);
        } else {
          sofa(x + 36, b - 16, -61, 40);
        }
      } else {
        dashboard(center - 33, t + 34, -119, 66, 32, index, colors.light);
        if ([4, 8, 9, 14, 15].includes(index)) server(r - 39, b - 56, -104);
        else if ([1, 12, 17, 19].includes(index)) shelf(r - 44, b - 59, -107, 32);
        else plant(r - 24, b - 3, -39, index + 10, .87);
        plant(x + 23, b - 3, -35, index + 2, .84);
      }
    }

    function actorLocations(room) {
      if (room.index === LOUNGE.index) return [];
      const center = (room.left + room.right) / 2;
      if (room.index === ORCHESTRATOR.index) return [{x: center, z: -30, size: 1.25, side: 0}];
      if (room.index === OWNER.index) return [{x: center + 13, z: -43, size: 1.06, side: 1}];
      return [
        {x: center - 36, z: -49, size: .86, side: 1},
        {x: center + 35, z: -47, size: .85, side: -1},
      ];
    }

    function drawFurniture(room) {
      const colors = roomTheme(room);
      const center = (room.left + room.right) / 2;
      const b = room.bottom;
      if (room.index === LOUNGE.index) return;
      if (room.index === ORCHESTRATOR.index) {
        box(center - 86, b - 26, -38, 172, 21, 36, '#426967', '#7ec0b4', '#24515b');
        facet([[center-85,b-26,-1], [center+85,b-26,-1], [center+85,b-14,-1],[center-85,b-14,-1]], 'rgba(92, 193, 180, .49)');
        edge([[center-86,b-26,0],[center+86,b-26,0]], colors.light, 2);
        edge([[center-85,b-9,0],[center+85,b-9,0]], '#78ddcc', 1);
        for (const x of [-70, -54, 54, 70]) laptop(center+x-8, b-27, -14, '#6ffff0');
        return;
      }
      if (room.index === OWNER.index) {
        table(center-43, b-32, -27, 112, {...colors, desk: '#e5b77b'}, true);
        laptop(center+27, b-36, -22, '#92eee1', true);
        plant(center+57, b-34, -25, 9, .34);
        return;
      }
      const separated = [3, 6, 7, 9, 11, 15, 16].includes(room.index);
      if (separated) {
        table(center - 69, b - 28, -22, 57, colors);
        table(center + 11, b - 28, -23, 57, colors);
      } else {
        table(center - 64, b - 28, -22, 128, colors, true);
      }
      laptop(center-45, b - 32, -21, colors.light, room.index === 5);
      laptop(center+28, b - 32, -20, colors.light);
      if (!separated) plant(center + 4, b - 31, -19, room.index, .29);
    }

    function robot(x, y, z, size, side, seed, working, time) {
      localAt(x, y, z, () => {
        brush.scale(size, size);
        brush.translate(0, Math.sin(time * (working ? 2.7 : 1.1) + seed) * 1.7);
        const sheen = brush.createLinearGradient(-15, -13, 15, 13);
        sheen.addColorStop(0, '#fdfdf5');
        sheen.addColorStop(.47, '#d7e7e5');
        sheen.addColorStop(1, '#7798a0');
        const shell = brush.createLinearGradient(-10, -45, 17, -23);
        shell.addColorStop(0, '#ffffff');
        shell.addColorStop(.54, '#d9e5e6');
        shell.addColorStop(1, '#7f9ca4');
        circle(0, -1, 12, 16, sheen);
        boxLimb(-8, 7, -9, 18, 5.7, '#b4cdd0');
        boxLimb(7, 8, 9, 18, 5.7, '#8ba9ae');
        circle(-9, 19, 6, 2.8, '#bdcdd0');
        circle(10, 19, 6, 2.8, '#a1b2b8');
        const lap = Math.sin(time * (working ? 8.4 : 1.5) + seed);
        const right = Math.cos(time * (working ? 7.2 : 1.2) + seed);
        boxLimb(-10, -8, -16, -3 + lap, 5.8, '#809fa5');
        boxLimb(-16, -3 + lap, -12 + 2 * side, 2 + lap * 2.3, 5.3, sheen);
        boxLimb(10, -7, 15, -4 + right, 5.8, '#a3bec0');
        boxLimb(15, -4 + right, 11 + 2 * side, 0 + right * 2.5, 5.4, sheen);
        circle(-12 + 2 * side, 2 + lap * 2.3, 3.3, 2.6, '#f1f7f3');
        circle(11 + 2 * side, right * 2.5, 3.3, 2.6, '#e9f3ef');
        circle(0, -14, 5.8, 4.2, '#a2c3c6');
        roundShape(-3.5, -4, 7, 2.8, 1, '#6ecaba');
        brush.save();
        brush.translate(side * (1.4 + Math.sin(time * 1.32 + seed) * 1.35), -25);
        brush.rotate(Math.sin(time * 1.36 + seed) * .078 + side * .05);
        circle(0, 0, 18, 14, shell);
        circle(-15.5, .2, 3.9, 6.2, '#93b3b7');
        circle(15.7, .2, 3.8, 6.1, '#95aeb0');
        const visor = brush.createLinearGradient(0, -7, 3, 9);
        visor.addColorStop(0, '#254955');
        visor.addColorStop(.51, '#102e3c');
        visor.addColorStop(1, '#081b2b');
        roundShape(-12 + side, -7, 24, 15, [6, 6, 8, 8], visor);
        const blink = Math.sin(time * .93 + seed * .63) > .991;
        for (const offset of [-5.2, 5.2]) circle(offset + side * 2, -.1, 1.9, blink ? .38 : 1.62, '#76ffe8');
        brush.beginPath();
        brush.arc(side * 1.3, 2, 2.45, .12, Math.PI - .12);
        brush.lineWidth = .82;
        brush.strokeStyle = '#88e2d9';
        brush.stroke();
        brush.restore();
      });
    }

    function boxLimb(x0, y0, x1, y1, thickness, color) {
      brush.beginPath();
      brush.moveTo(x0, y0);
      brush.lineTo(x1, y1);
      brush.lineWidth = thickness;
      brush.lineCap = 'round';
      brush.strokeStyle = color;
      brush.stroke();
    }

    function architecture() {
      const side = sinYaw < 0 ? 0 : WIDTH;
      const outside = side + (side === 0 ? -10 : 10);
      facet([[outside, 52, -131], [outside, 52, 15], [outside, BOTTOM + 3, 15],
        [outside, BOTTOM + 3, -131]], 'rgba(105, 161, 160, .27)');
      for (let level = 0; level < 6; level += 1) {
        const y = level === 0 ? 55 : 170 + (level-1) * 111;
        box(-10, y - 2, 4, WIDTH + 20, 6, 13, '#7f9697', '#e3d6bb', '#607978');
        edge([[-8, y+.3, 18], [1007, y+.3, 18]], '#fbefd8', .95);
        edge([[-8, y+3.6, 18], [1007, y+3.6, 18]], '#344c51', .55);
      }
      for (const border of [0, 200, 400, 600, 800, WIDTH]) {
        box(border-3.5, 170, 4, 7, BOTTOM - 170, 13, '#7d9b9a', '#d4cbb4', '#425c62');
        edge([[border-1, 173, 18], [border-1, BOTTOM-2, 18]], '#d4d8c6', .85);
      }
      for (const border of [0, 285, 740, WIDTH]) {
        box(border-3.5, 50, 4, 7, 120, 13, '#87a4a4', '#dac7a9', '#4b6569');
        edge([[border-1, 55, 18], [border-1, 168, 18]], '#e1dacf', .8);
      }
      box(-18, BOTTOM + 2, -5, WIDTH + 36, 11, 26, '#7a8e8c', '#bbb8a8', '#385258');
      edge([[-17, BOTTOM + 2, 22], [1017, BOTTOM + 2, 22]], '#e6dcc7', 1.1);
      facet([[-13, 51, 15], [1013, 51, 15], [996, 20, -124], [5, 20, -124]], '#9da7a6');
      facet([[7, 46, 6], [993, 46, 6], [987, 25, -106], [12, 25, -106]], '#45686e');
      edge([[-12, 52, 16], [1012, 52, 16]], '#ffe7b7', 2);
      facet([[215, 50, 28], [785, 50, 28], [755, 4, 12], [245, 4, 12]], '#1b494a');
      edge([[215, 50, 28], [245, 4, 12], [755, 4, 12], [785, 50, 28], [215, 50, 28]], '#ffd99c', 2.7);
      edge([[225, 47, 28], [775, 47, 28]], '#af936f', .65);
    }

    function glass(room) {
      const {left: l, right: r, top: t, bottom: b} = room;
      const colors = roomTheme(room);
      facet([[l+5,t+7,9], [l+16,t+7,9], [l+11,b-1,9], [l+5,b-1,9]], 'rgba(156,231,229,.15)');
      facet([[r-9,t+7,9], [r-4,t+7,9], [r-4,b-1,9], [r-12,b-1,9]], 'rgba(170,232,226,.18)');
      edge([[l+7, t+10, 10], [l+7, b-4, 10]], colors.trim, .85);
      edge([[r-7, t+10, 10], [r-7, b-4, 10]], colors.trim, .75);
      if (selected === room.index) {
        edge([[l+7,t+6,19], [r-7,t+6,19], [r-7,b-3,19], [l+7,b-3,19], [l+7,t+6,19]], '#e9ffec', 1.6);
        edge([[l+9,b-4,20], [r-9,b-4,20]], colors.light, 2.3);
      } else if (activeRooms.has(room.index)) {
        edge([[l+9,b-2,20], [r-9,b-2,20]], '#ffd395', 1.9);
      }
    }

    function geometry() {
      sinYaw = Math.sin(yaw * DEGREE);
      cosYaw = Math.cos(yaw * DEGREE);
      sinPitch = Math.sin((pitch + 10) * DEGREE);
      cosPitch = Math.cos((pitch + 10) * DEGREE);
      scale = Math.min(width / 1055, height / 673) * zoom;
    }

    function rebuild() {
      if (!width || !height || destroyed) return;
      geometry();
      brush = baseContext;
      brush.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      brush.clearRect(0,0,width,height);
      glow(500, BOTTOM + 19, 9, 550, 25, DARK, .48);
      for (const room of [...ROOMS].reverse()) {
        drawDepth(room);
        for (const actor of actorLocations(room)) chair(actor.x, room.bottom - 28, actor.z - 7);
      }
      brush = overlayContext;
      brush.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      brush.clearRect(0,0,width,height);
      for (const room of ROOMS) {
        drawFurniture(room);
        glass(room);
      }
      architecture();
      brush = context;
      paint();
      const metadata = (x, y, z, w, h) => {
        const point = project(x, y, z);
        return {
          x: point.x / width, y: point.y / height,
          width: (w * point.size) / width, height: (h * point.size) / height,
        };
      };
      const roomLabel = ({left, right, top, bottom}) => {
        const center = (left + right) / 2;
        return {
          ...metadata(center, top + 16, 12, right - left - 16, 25),
          body: metadata(center, (top + bottom) / 2, 14, right - left - 11, bottom - top - 9),
        };
      };
      onPositions({
        rooms: DEPARTMENTS.map(roomLabel),
        owner: roomLabel(OWNER),
        orchestrator: roomLabel(ORCHESTRATOR),
        sign: metadata(500, 26, 30, 526, 40),
      });
    }

    function paint() {
      if (!width || !height || destroyed) return;
      brush = context;
      brush.setTransform(1, 0, 0, 1, 0, 0);
      brush.clearRect(0, 0, canvas.width, canvas.height);
      brush.drawImage(base, 0, 0);
      brush.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      for (const room of ROOMS) {
        const working = activeRooms.has(room.index);
        const center = (room.left + room.right) / 2;
        if (working || room.index === ORCHESTRATOR.index) {
          const pulse = .11 + Math.sin(sceneTime * 2.1 + room.index) * .045;
          glow(center, room.top + 48, -115, (room.right - room.left) * .33, 18, roomTheme(room).light, pulse);
        }
        actorLocations(room).forEach((actor, n) => {
          const seed = room.index * 1.93 + n * 2.43;
          robot(actor.x, room.bottom - 37, actor.z, actor.size, actor.side, seed, working, sceneTime);
        });
      }
      brush.setTransform(1, 0, 0, 1, 0, 0);
      brush.drawImage(overlay, 0, 0);
    }

    function frame(timestamp) {
      timer = 0;
      if (!motion || destroyed || document.hidden) return;
      if (!lastFrame) lastFrame = timestamp;
      if (timestamp - lastFrame >= 33) {
        sceneTime += Math.min(timestamp - lastFrame, 82) / 1000;
        lastFrame = timestamp;
        paint();
      }
      timer = window.requestAnimationFrame(frame);
    }

    function updateLoop() {
      if (timer) window.cancelAnimationFrame(timer);
      timer = 0;
      lastFrame = 0;
      if (motion && !destroyed && !document.hidden) timer = window.requestAnimationFrame(frame);
    }

    function resize() {
      const nextWidth = canvas.clientWidth;
      const nextHeight = canvas.clientHeight;
      const nextRatio = Math.min(window.devicePixelRatio || 1, 2);
      if (!nextWidth || !nextHeight || (nextWidth === width && nextHeight === height && nextRatio === pixelRatio)) return;
      width = nextWidth;
      height = nextHeight;
      pixelRatio = nextRatio;
      for (const surface of [canvas, base, overlay]) {
        surface.width = Math.round(width * pixelRatio);
        surface.height = Math.round(height * pixelRatio);
      }
      rebuild();
    }

    function setCamera(values = {}) {
      const nextYaw = Number.isFinite(values.yaw) ? Math.max(-18, Math.min(18, values.yaw)) : yaw;
      const nextPitch = Number.isFinite(values.pitch) ? Math.max(-8, Math.min(12, values.pitch)) : pitch;
      const nextZoom = Number.isFinite(values.zoom) ? Math.max(.8, Math.min(1.42, values.zoom)) : zoom;
      if (nextYaw === yaw && nextPitch === pitch && nextZoom === zoom) return;
      yaw = nextYaw;
      pitch = nextPitch;
      zoom = nextZoom;
      rebuild();
    }

    function setRooms({active = [], selected: current = -1} = {}) {
      const next = new Set(active);
      if (current === selected && next.size === activeRooms.size && [...next].every(index => activeRooms.has(index))) return;
      activeRooms = next;
      selected = current;
      rebuild();
    }

    function setMotion(enabled) {
      motion = Boolean(enabled);
      updateLoop();
      paint();
    }

    function destroy() {
      destroyed = true;
      resizeObserver.disconnect();
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', updateLoop);
      updateLoop();
    }

    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', updateLoop);
    resize();
    updateLoop();
    return {setCamera, setRooms, setMotion, destroy};
  }

  window.createOfficeScene = createOfficeScene;
})();
