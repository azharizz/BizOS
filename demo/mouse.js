// Mouse driver for demo footage (macOS, built-in JXA, needs Accessibility permission). Coordinates are logical points.
//   osascript -l JavaScript demo/mouse.js move X Y | click X Y | hold X Y MS | scroll DY
ObjC.import('ApplicationServices')
ObjC.import('Foundation')
const post = (type, x, y) => $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent(null, type, $.CGPointMake(x, y), 0))
const sleep = (s) => $.NSThread.sleepForTimeInterval(s)
function where() { const p = $.CGEventGetLocation($.CGEventCreate(null)); return [p.x, p.y] }
function glide(x, y) {  // a visible, human-speed move: the footage shows where the pointer goes
  const [x0, y0] = where(), n = 28
  for (let i = 1; i <= n; i++) { const t = i / n, e = t * t * (3 - 2 * t); post(5, x0 + (x - x0) * e, y0 + (y - y0) * e); sleep(0.016) }
}
function run(argv) {
  const [cmd, a, b, c] = argv, x = +a, y = +b
  if (cmd === 'move') glide(x, y)
  else if (cmd === 'click') { glide(x, y); sleep(0.25); post(1, x, y); sleep(0.08); post(2, x, y) }
  else if (cmd === 'hold') { glide(x, y); sleep(0.25); post(1, x, y); sleep((+c || 1500) / 1000); post(2, x, y) }
  else if (cmd === 'scroll') { $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateScrollWheelEvent(null, 0, 1, +a)) }
  return 'ok'
}
