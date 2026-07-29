static const char htmlContent[] PROGMEM = R"HTML(
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Draggable Circle Canvas</title>
  <style>
    body {
      margin: 0;
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
      background: #f0f0f0;
    }
    canvas {
      border: 2px solid #333;
      background: #fff;
    }
  </style>
</head>
<body>

<canvas id="canvas" width="475" height="400"></canvas>
<div style="margin: 10px; padding: 10px">
  <p id="xPos">pos x: 100</p>   
  <p id="yPos">pos y: 200</p>
  <button id="submit" onclick="sendMessage('p')">go to</button>
  <button id="home" onclick="sendMessage('h')">home</button>
  <button id="servo_up" onclick="sendMessage('u')">servo up</button>
  <button id="servo_down" onclick="sendMessage('d')">servo down</button>
  <button id="circle" onclick="sendMessage('c')">draw circle</button>
</div>

<script>
  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d");
  const xPos = document.getElementById("xPos");
  const yPos = document.getElementById("yPos");

  const circle = {
    x: 100,
    y: 200,
    radius: 10,
    dragging: false
  };

  function updateText(x, y){
    xPos.innerHTML = `pos x: ${Math.floor(x)}`;
    yPos.innerHTML = `pos y: ${Math.floor(y)}`;
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.beginPath();
    ctx.arc(circle.x, circle.y, circle.radius, 0, Math.PI * 2);
    ctx.strokeStyle = "red";
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.closePath();

    ctx.beginPath();
    ctx.moveTo(circle.x - circle.radius, circle.y);
    ctx.lineTo(circle.x + circle.radius, circle.y);
    ctx.strokeStyle = "red";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.closePath();

    ctx.beginPath();
    ctx.moveTo(circle.x, circle.y - circle.radius);
    ctx.lineTo(circle.x, circle.y + circle.radius);
    ctx.strokeStyle = "red";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.closePath();

    updateText(circle.x, canvas.height - circle.y);
  }

  function isMouseInCircle(mx, my) {
    const dx = mx - circle.x;
    const dy = my - circle.y;
    return Math.sqrt(dx * dx + dy * dy) <= circle.radius;
  }

  canvas.addEventListener("mousedown", (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    if (isMouseInCircle(mx, my)) {
      circle.dragging = true;
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!circle.dragging) return;

    const rect = canvas.getBoundingClientRect();
    let mx = e.clientX - rect.left;
    let my = e.clientY - rect.top;

    mx = Math.max(0, Math.min(canvas.width, mx));
    my = Math.max(0, Math.min(canvas.height, my));

    circle.x = mx;
    circle.y = my;

    draw();
  });

  canvas.addEventListener("mouseup", () => circle.dragging = false);
  canvas.addEventListener("mouseleave", () => circle.dragging = false);

  draw();

  var ws = new WebSocket('ws://192.168.4.1/ws');
  ws.onopen = () => console.log("WebSocket connected");
  ws.onmessage = e => console.log("WebSocket message: " + e.data);
  ws.onclose = () => console.log("WebSocket closed");
  ws.onerror = e => console.log("WebSocket error: " + e);

  function sendMessage(messageType) {
    if (messageType === 'p') {
      ws.send(`${Math.floor(circle.x)},${Math.floor(canvas.height - circle.y)}`);
    } else if (messageType === 'd' || messageType === 'u' || messageType === 'h' || messageType === 'c') {
      ws.send(messageType);
    }
  }
</script>

</body>
</html>
)HTML";