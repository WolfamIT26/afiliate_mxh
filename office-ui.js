'use strict';

const byId = id => document.getElementById(id);
const initial = JSON.parse(byId('office-data').textContent);
const live = initial.mode === 'live';
const canvas = byId('building');
const labels = byId('room-labels');
const picker = byId('room-picker');
const title = byId('detail-title');
const notes = byId('detail-note');
const taskList = byId('task-list');
const refresh = byId('refresh');
const motionButton = byId('motion');
const mobile = window.matchMedia('(max-width: 980px)');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const front = {yaw: 0, pitch: 3, zoom: 1};
const camera = {...front};
const leaders = [
  {key: 'owner', name: 'Owner', note: 'Theo dõi tiến độ và xem kết quả bàn giao theo phòng.'},
  {key: 'orchestrator', name: 'Master Orchestrator', note: 'Tổng hợp phiếu công việc của các phòng ban.'},
];

let rooms = initial.rooms;
let motion = !reducedMotion.matches;
let selected;
let rendered = '';
let isRefreshing = false;
let positions;
let drag;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

const roomButtons = rooms.slice(0, 20).map((room, index) => makeLabel(String(index), room.name));
const topButtons = leaders.map(leader => makeLabel(leader.key, leader.name, true));
for (const leader of leaders) addOption(leader.key, leader.name);
rooms.forEach((room, index) => addOption(String(index), room.name));
picker.addEventListener('change', () => select(picker.value));

function addOption(value, text) {
  const option = element('option', text);
  option.value = value;
  picker.append(option);
}

function makeLabel(key, text, executive = false) {
  const node = element('button', text, executive ? 'room-label executive' : 'room-label');
  node.type = 'button';
  node.dataset.room = key;
  node.setAttribute('aria-controls', 'department-detail');
  node.addEventListener('click', () => select(key, true));
  labels.append(node);
  return node;
}

function place(node, point) {
  if (!point) return;
  node.style.left = `${point.x * 100}%`;
  node.style.top = `${point.y * 100}%`;
  node.style.visibility = 'visible';
}

const scene = typeof window.createOfficeScene === 'function' ? window.createOfficeScene(canvas, {
  onPositions(next) {
    positions = next;
    for (const [index, node] of roomButtons.entries()) place(node, next.rooms[index]);
    for (const [index, node] of topButtons.entries()) place(node, next[leaders[index].key]);
    place(byId('roof-title'), next.sign);
  },
}) : null;

function totals() {
  return rooms.reduce((sum, room) => ({
    pending: sum.pending + room.pending,
    running: sum.running + room.running,
    done: sum.done + room.done,
  }), {pending: 0, running: 0, done: 0});
}

function updateScene() {
  if (scene) scene.setRooms({
    active: rooms.flatMap((room, index) => room.running > 0 ? [index] : []),
    selected: /^\d+$/.test(selected) ? Number(selected) : -1,
  });
  for (const [index, button] of roomButtons.entries()) {
    const room = rooms[index];
    button.classList.toggle('active', room.running > 0);
    button.setAttribute('aria-pressed', String(button.dataset.room === selected));
    const state = room.running ? `${room.running} đang làm` : room.done ? `${room.done} đã bàn giao` :
      room.pending ? `${room.pending} chờ nhận` : 'Chưa có phiếu';
    button.title = `${room.name} · ${state}`;
    button.setAttribute('aria-label', `${room.name}, ${state}`);
  }
  for (const button of topButtons) button.setAttribute('aria-pressed', String(button.dataset.room === selected));
}

function taskDetails(task) {
  const card = element('details', undefined, 'task');
  card.dataset.taskId = task.id;
  card.append(element('summary', task.title));
  card.append(element('small', `${task.assignee} · ${task.page} · ${task.status}`));
  if (task.output) card.append(element('p', task.output));
  if (live) {
    const link = element('a', 'Mở phiếu công việc');
    link.href = `/#task-${task.id}`;
    card.append(link);
  }
  return card;
}

function updateDetail() {
  const leader = leaders.find(item => item.key === selected);
  const room = leader ? totals() : rooms[Number(selected)];
  const tasks = leader ? rooms.flatMap(current => current.tasks).sort((a, b) => b.id - a.id).slice(0, 6) : room.tasks;
  const key = JSON.stringify([selected, room, tasks]);
  if (key === rendered) return;
  rendered = key;
  const open = new Set(Array.from(taskList.querySelectorAll('details[open]'), node => node.dataset.taskId));
  byId('detail-label').textContent = leader ? 'Tầng điều hành' : 'Phòng ban';
  title.textContent = leader ? leader.name : room.name;
  notes.textContent = leader?.note || '';
  for (const status of ['pending', 'running', 'done']) byId(`count-${status}`).textContent = room[status];
  taskList.replaceChildren();
  if (!tasks.length) {
    taskList.append(element('p', 'Chưa có phiếu công việc.'));
  } else {
    for (const task of tasks) {
      const card = taskDetails(task);
      card.open = open.has(card.dataset.taskId);
      taskList.append(card);
    }
    if (!leader && tasks.length < room.pending + room.running + room.done) {
      taskList.append(element('p', 'Đang hiện các phiếu đang làm, đang chờ và mới bàn giao.'));
    }
  }
}

function select(key, fromScene = false, save = true) {
  if (!Array.from(picker.options).some(option => option.value === key)) return;
  selected = key;
  picker.value = key;
  updateScene();
  updateDetail();
  if (save) history.replaceState(null, '', `#department-${key}`);
  if (fromScene && mobile.matches) {
    title.scrollIntoView({block: 'center', behavior: motion ? 'smooth' : 'instant'});
  }
}

function applyCamera() {
  scene?.setCamera(camera);
  byId('zoom-out').disabled = camera.zoom <= .8;
  byId('zoom-in').disabled = camera.zoom >= 1.75;
}

function zoom(change) {
  camera.zoom = Math.min(1.75, Math.max(.8, Math.round((camera.zoom + change) * 100) / 100));
  applyCamera();
}

function applyMotion() {
  scene?.setMotion(motion);
  motionButton.textContent = motion ? 'Tạm dừng' : 'Phát chuyển động';
  motionButton.setAttribute('aria-pressed', String(motion));
}

byId('front').addEventListener('click', () => { Object.assign(camera, front); applyCamera(); });
byId('zoom-out').addEventListener('click', () => zoom(-.15));
byId('zoom-in').addEventListener('click', () => zoom(.15));
motionButton.addEventListener('click', () => { motion = !motion; applyMotion(); });
reducedMotion.addEventListener('change', event => { motion = !event.matches; applyMotion(); });

canvas.addEventListener('pointerdown', event => {
  if (!event.isPrimary || event.button !== 0) return;
  canvas.setPointerCapture(event.pointerId);
  drag = {id: event.pointerId, x: event.clientX, y: event.clientY, yaw: camera.yaw, pitch: camera.pitch, moved: false};
  canvas.classList.add('is-dragging');
});
canvas.addEventListener('pointermove', event => {
  if (!drag || drag.id !== event.pointerId) return;
  const dx = event.clientX - drag.x;
  const dy = event.clientY - drag.y;
  if (!drag.moved && Math.hypot(dx, dy) < 5) return;
  drag.moved = true;
  camera.yaw = Math.max(-24, Math.min(24, drag.yaw + dx * .13));
  camera.pitch = Math.max(-5, Math.min(15, drag.pitch - dy * .11));
  applyCamera();
});
function endDrag(event) {
  if (!drag || drag.id !== event.pointerId) return;
  if (!drag.moved && event.type === 'pointerup' && positions) {
    const bounds = canvas.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width;
    const y = (event.clientY - bounds.top) / bounds.height;
    const contains = ({body}) => body && Math.abs(x - body.x) <= body.width / 2 &&
      Math.abs(y - body.y) <= body.height / 2;
    const leader = leaders.find(({key}) => contains(positions[key]));
    const department = positions.rooms.findIndex(contains);
    if (leader) select(leader.key, true);
    else if (department >= 0) select(String(department), true);
  }
  drag = undefined;
  canvas.classList.remove('is-dragging');
}
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);
canvas.addEventListener('lostpointercapture', endDrag);

async function refreshRooms(manual = false) {
  if (!live || isRefreshing || (!manual && document.hidden)) return;
  isRefreshing = true;
  try {
    const reply = await fetch('/office/tasks', {cache: 'no-store', signal: AbortSignal.timeout(8000)});
    if (!reply.ok) throw new Error('Không nhận được dữ liệu');
    rooms = (await reply.json()).rooms;
    updateScene();
    updateDetail();
    byId('refresh-status').textContent = manual ? 'Đã cập nhật phiếu.' : '';
  } catch {
    byId('refresh-status').textContent = 'Chưa cập nhật được phiếu.';
  } finally {
    isRefreshing = false;
  }
}

refresh.hidden = !live;
byId('dashboard-link').hidden = !live;
byId('view-mode').textContent = live ? 'Phiếu công việc trực tiếp' : 'Bản xem thử · dữ liệu đã bàn giao';
refresh.addEventListener('click', () => refreshRooms(true));
if (live) {
  window.setInterval(refreshRooms, 15000);
  document.addEventListener('visibilitychange', () => refreshRooms());
}
const incoming = location.hash.match(/^#department-([a-z]+|\d+)$/)?.[1];
const defaultRoom = rooms.findIndex(room => room.running);
const initialRoom = incoming && Array.from(picker.options).some(option => option.value === incoming) ?
  incoming : defaultRoom >= 0 ? String(defaultRoom) : 'orchestrator';
select(initialRoom, false, false);
applyCamera();
applyMotion();
