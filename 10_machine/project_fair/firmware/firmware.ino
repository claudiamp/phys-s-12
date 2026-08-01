/*
Project fair version. Based on the week 10 sketch (code updated by Bobby
McCarthy 4/19/2026), intended for Xiao Esp32c3.

The only difference from week 10: the board joins an existing network instead
of hosting its own, and answers to a name so nothing has to know its IP.

Using Libraries:
- Async TCP 3.4.10 https://github.com/ESP32Async/AsyncTCP
- ESP Async WebServer 3.10.3 https://github.com/ESP32Async/ESPAsyncWebServer
- AccelStepper 1.64 https://www.airspayce.com/mikem/arduino/AccelStepper/
- ESP32Servo 3.13 https://github.com/madhephaestus/ESP32Servo

How To Use:
  - Copy secrets.example.h to secrets.h and fill in the network
  - Flash, then open the serial monitor at 115200 to see which mode it came up in
  - On the network:  http://plotter.local
  - No network:      it falls back to the esp-captive AP at 192.168.4.1
*/


#include <AsyncTCP.h>
#include <WiFi.h>
#include <ESPmDNS.h>

#include <ESPAsyncWebServer.h>
#include "html.h"
#include "secrets.h"

#include <AccelStepper.h>
#include <ESP32Servo.h>
#include <LittleFS.h>

// How long to wait for the network before giving up and hosting our own.
const uint32_t STA_TIMEOUT_MS = 10000;

const int xLimit = D8;
const int yLimit = D7;

const int stepPinX = D1;
const int dirPinX = D5;
const int stepPinY = D3;
const int dirPinY = D2;
float pulleyDiamX = 12.22;
float pulleyDiamY = 12.22;
const int xMicrosteps = 16;
const int yMicrosteps = 16;
const int stepsPerRev = 200;

const float xMmtoSteps = (xMicrosteps*stepsPerRev)/(pulleyDiamX*PI);
const float yMmtoSteps = (yMicrosteps*stepsPerRev)/(pulleyDiamY*PI);

const int servoPin = D4;
const int SERVO_DOWN = 90;
const int SERVO_UP = 160;
volatile bool isHoming = false;

AccelStepper stepperX(AccelStepper::DRIVER, stepPinX, dirPinX);
AccelStepper stepperY(AccelStepper::DRIVER, stepPinY, dirPinY);

static AsyncWebServer server(80);

// create an easy-to-use handler
static AsyncWebSocketMessageHandler wsHandler;

// add it to the websocket server
static AsyncWebSocket ws("/ws", wsHandler.eventHandler());

Servo servo;

volatile int currXPos = 0;
volatile int currYPos = 0;

volatile int servoPos = SERVO_UP;
volatile bool updateServo = true;

// ---- test circle ----
const float CIRCLE_CX = 50.0;   // mm from home corner
const float CIRCLE_CY = 50.0;
const float CIRCLE_R  = 20.0;
const int   CIRCLE_SEGMENTS = 48;
const float DOT_R = 0.8;        // the dot in the middle
const int   DOT_SEGMENTS = 8;
const float DRAW_SPEED = 1200;  // steps/s
const float DRAW_ACCEL = 4000;  // steps/s^2
volatile bool drawCircle = false;

// ---- gcode file ----
// Measured travel, not the frame size. runFile() aborts a job the moment a
// move lands outside this, so it has to cover the far corner of the top row:
// a drawing whose origin is y=130 reaches roughly y=225.
const float BED_W_MM = 350.0;
const float BED_H_MM = 250.0;
volatile bool drawFile = false;
volatile bool stopFile = false;
float originXmm = 0;            // where the job starts, captured when 'g' runs
float originYmm = 0;

// blocking move, both axes scaled so they arrive together
void moveToMm(float xmm, float ymm) {
  long tx = lroundf(xmm * xMmtoSteps);
  long ty = lroundf(ymm * yMmtoSteps);
  long dx = labs(tx - stepperX.currentPosition());
  long dy = labs(ty - stepperY.currentPosition());
  if (dx == 0 && dy == 0) return;          // avoids a 0/0 speed ratio

  float vx = DRAW_SPEED, vy = DRAW_SPEED, ax = DRAW_ACCEL, ay = DRAW_ACCEL;
  if (dx >= dy) { float k = (float)dy / (float)dx; vy = fmaxf(vy * k, 1.0f); ay = fmaxf(ay * k, 1.0f); }
  else          { float k = (float)dx / (float)dy; vx = fmaxf(vx * k, 1.0f); ax = fmaxf(ax * k, 1.0f); }

  stepperX.setMaxSpeed(vx); stepperX.setAcceleration(ax); stepperX.moveTo(tx);
  stepperY.setMaxSpeed(vy); stepperY.setAcceleration(ay); stepperY.moveTo(ty);
  static uint32_t lastTick = 0;
  while (stepperX.distanceToGo() || stepperY.distanceToGo()) {
    stepperX.run(); stepperY.run();
    if (millis() - lastTick >= 20) { lastTick = millis(); delay(1); }
  }
}

void penTo(int target) {
  static int actual = SERVO_UP;          // setup() leaves it here
  if (target == actual) return;          // already there, nothing to do
  int inc = (target > actual) ? 1 : -1;
  for (int i = actual; i != target; i += inc) { servo.write(i); delay(5); }
  servo.write(target);
  actual = target;
  servoPos = target;
  delay(150);
}

void ring(float cx, float cy, float r, int segs) {
  penTo(SERVO_UP);
  moveToMm(cx + r, cy);
  penTo(SERVO_DOWN);
  for (int i = 1; i <= segs; i++) {
    float a = 2.0f * PI * i / segs;
    moveToMm(cx + r * cosf(a), cy + r * sinf(a));
  }
  penTo(SERVO_UP);
}

// finds a word like "X29.4" and returns its value, or def if the letter is absent
float getWord(const char *s, char letter, float def) {
  for (const char *p = s; *p; p++) {
    if (toupper(*p) == letter) {
      char *e;
      float v = strtof(p + 1, &e);
      if (e != p + 1) return v;
    }
  }
  return def;
}

void runFile() {
  // A stop pressed while nothing was drawing latches this flag with no job
  // running to clear it, and then every job after that exits before drawing a
  // single line. Start every job from a clean slate.
  stopFile = false;

  File f = LittleFS.open("/job.gcode", FILE_READ);
  if (!f) { Serial.println("no job file"); return; }

  // wherever the head is sitting right now becomes gcode X0 Y0
  originXmm = stepperX.currentPosition() / xMmtoSteps;
  originYmm = stepperY.currentPosition() / yMmtoSteps;
  Serial.printf("origin %.1f, %.1f\n", originXmm, originYmm);

  float x = 0, y = 0;
  bool offBed = false;
  char line[128];

  while (f.available() && !stopFile) {
    int n = f.readBytesUntil('\n', line, sizeof(line) - 1);
    line[n] = 0;
    char *c = strchr(line, ';');
    if (c) *c = 0;                          // drop the comment

    float m = getWord(line, 'M', -1);
    if (m == 3) { penTo(SERVO_DOWN); continue; }
    if (m == 5) { penTo(SERVO_UP);   continue; }

    float g = getWord(line, 'G', -1);
    if (g == 4) { delay((int)getWord(line, 'P', 0)); continue; }

    if (g == 0 || g == 1) {
      x = getWord(line, 'X', x);            // no X on the line = keep the old one
      y = getWord(line, 'Y', y);
      float px = x + originXmm;             // x and y stay raw, only px/py get the offset
      float py = y + originYmm;
      if (px < 0 || py < 0 || px > BED_W_MM || py > BED_H_MM) {
        Serial.println("off the bed, stopping");
        offBed = true;
        break;
      }
      moveToMm(px, py);
    }
  }

  f.close();
  penTo(SERVO_UP);

  // Tell whoever is listening how this ended. Without it the server has no way
  // to know a job finished -- it would sit there claiming the machine is still
  // drawing until somebody clicked a button.
  //
  // The three endings are not the same thing: only "done" means the whole file
  // was drawn, and only that one should be filed as a finished drawing.
  const char *how = stopFile ? "stopped" : (offBed ? "aborted" : "done");
  ws.textAll(how);

  stopFile = false;
  Serial.printf("file %s\n", how);
}

// Join the network from secrets.h. If it isn't there after STA_TIMEOUT_MS,
// host the old access point instead so the machine is never unreachable.
// Either way we come up as MDNS_NAME.local, so nothing downstream has to care
// which mode won.
void startNetwork() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);            // keep the server responsive
  WiFi.setAutoReconnect(true);     // it's a long day, the AP will blip
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("joining %s ", WIFI_SSID);
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < STA_TIMEOUT_MS) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("connected, IP ");
    Serial.println(WiFi.localIP());   // <- write this down, it's the fallback
                                      //    for when mDNS is filtered
  } else {
    Serial.println("no network, falling back to the access point");
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID);
    Serial.print("AP up, IP ");
    Serial.println(WiFi.softAPIP());
  }

  // Has to come after the connection settles, not in setup() before it.
  if (MDNS.begin(MDNS_NAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("http://%s.local\n", MDNS_NAME);
  } else {
    Serial.println("mDNS failed, use the IP above");
  }
}

void setup() {
  Serial.begin(115200);
  startNetwork();
  pinMode(xLimit, INPUT_PULLUP);
  pinMode(yLimit, INPUT_PULLUP);
  pinMode(stepPinX, OUTPUT);
  pinMode(dirPinX, OUTPUT);
  pinMode(stepPinY, OUTPUT);
  pinMode(dirPinY, OUTPUT);

  digitalWrite(stepPinX, LOW);
  digitalWrite(stepPinY, LOW);
  digitalWrite(dirPinY, LOW);
  digitalWrite(dirPinX, LOW);
  stepperX.setAcceleration(1000);
  stepperX.setMaxSpeed(2000);
  stepperX.setPinsInverted(true, false, false);
  stepperY.setAcceleration(1000);
  stepperY.setMaxSpeed(2000);

  servo.setPeriodHertz(50);    // standard 50 hz servo
	servo.attach(servoPin, 1000, 2000);
  // stepperX.moveTo(3200);
  // stepperY.moveTo(100);

  if (!LittleFS.begin(true)) Serial.println("LittleFS mount failed");

  // serves root html page
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", (const uint8_t *)htmlContent, sizeof(htmlContent)/ sizeof(htmlContent[0]));
  });

  // receives the .gcode file and stores it in flash
  server.on("/upload", HTTP_POST,
    [](AsyncWebServerRequest *request) { request->send(200, "text/plain", "stored"); },
    [](AsyncWebServerRequest *request, const String &name, size_t index,
       uint8_t *data, size_t len, bool final) {
      static File up;
      if (!index) {
        if (drawFile) { request->send(409, "text/plain", "busy"); return; }
        up = LittleFS.open("/job.gcode", FILE_WRITE);   // replaces any old file
      }
      if (up) up.write(data, len);
      if (final && up) { up.close(); Serial.printf("upload %u bytes\n", index + len); }
    });

  wsHandler.onConnect([](AsyncWebSocket *server, AsyncWebSocketClient *client) {
    Serial.printf("Client %" PRIu32 " connected\n", client->id());
    server->textAll("New client: " + String(client->id()));
  });

  wsHandler.onDisconnect([](AsyncWebSocket *server, uint32_t clientId) {
    Serial.printf("Client %" PRIu32 " disconnected\n", clientId);
    server->textAll("Client " + String(clientId) + " disconnected");
  });

  wsHandler.onError([](AsyncWebSocket *server, AsyncWebSocketClient *client, uint16_t errorCode, const char *reason, size_t len) {
    Serial.printf("Client %" PRIu32 " error: %" PRIu16 ": %s\n", client->id(), errorCode, reason);
  });
  //data comes in the format of xPos,yPos
  wsHandler.onMessage([](AsyncWebSocket *server, AsyncWebSocketClient *client, const uint8_t *data, size_t len) {
    Serial.printf("Client %" PRIu32 " data: %s\n", client->id(), (const char *)data);
    bool isFirstNum = true;
    int targetXPos = 0;
    int targetYPos = 0;

    if(len == 1){
      switch((char)data[0]){
        case('u'):
          servoPos = SERVO_UP;
          updateServo = true;
        break;
        case('d'):
          servoPos = SERVO_DOWN;
          updateServo = true;
        break;
        case('h'):
          isHoming = true;
        break;
        case('c'):
          drawCircle = true;
        break;
        case('g'):
          drawFile = true;
        break;
        case('s'):
          stopFile = true;
        break;
        default:
        break;
      }
      return;
    }

    for(int i = 0; i < len; i++){
      if (data[i] == ','){
        isFirstNum = false;
        continue;
      }
      if(isFirstNum){
        targetXPos = targetXPos * 10 + (data[i] - '0');
      }
      else{
        targetYPos = targetYPos * 10 + (data[i] - '0');
      }
    }
    long targetXPosSteps = targetXPos * xMmtoSteps;
    long targetYPosSteps = targetYPos * yMmtoSteps;

    Serial.printf("targetXPosSteps %ld, targetYPosSteps: %ld\n", targetXPosSteps, targetYPosSteps);

    unsigned long distanceX = abs(targetXPosSteps - stepperX.currentPosition());
    unsigned long distanceY = abs(targetYPosSteps - stepperY.currentPosition());
    float distRatio = distanceX/((float)distanceY);
    stepperX.setAcceleration(distRatio > 1 ? 1000 : 1000*distRatio);
    stepperX.setMaxSpeed(distRatio > 1 ? 1000: 1000*distRatio);
    stepperX.moveTo(targetXPosSteps);
    stepperY.setAcceleration(distRatio > 1 ? 1000/distRatio: 1000);
    stepperY.setMaxSpeed(distRatio > 1 ? 1000/distRatio: 1000);
    stepperY.moveTo(targetYPosSteps);
  });

  wsHandler.onFragment([](AsyncWebSocket *server, AsyncWebSocketClient *client, const AwsFrameInfo *frameInfo, const uint8_t *data, size_t len) {
    Serial.printf("Client %" PRIu32 " fragment %" PRIu32 ": %s\n", client->id(), frameInfo->num, (const char *)data);
  });

  server.addHandler(&ws);
  server.begin();


}

void loop() {
  if(isHoming){
    stepperX.setSpeed(-600);
    stepperY.setSpeed(-600);
    while((digitalRead(xLimit) == 1 || digitalRead(yLimit) == 1)){
      if(digitalRead(xLimit) == 1){
        stepperX.runSpeed();
      }
      if(digitalRead(yLimit) == 1){
        stepperY.runSpeed();
      }
    }
    stepperX.setCurrentPosition(0);
    stepperY.setCurrentPosition(0);
    isHoming = false;
    ws.textAll("homed");     // homing is slow and silent; say when it is over
  }

  if(drawCircle){
    drawCircle = false;
    ring(CIRCLE_CX, CIRCLE_CY, CIRCLE_R, CIRCLE_SEGMENTS);
    ring(CIRCLE_CX, CIRCLE_CY, DOT_R, DOT_SEGMENTS);
  }

  if(drawFile){
    runFile();
    drawFile = false;   // stays true for the whole job, so uploads are blocked
  }
  

  if(updateServo){
    Serial.println("updating servo");
    Serial.println(servoPos);
    int endPos = servoPos;
    int startPos = servoPos == SERVO_UP ? SERVO_DOWN: SERVO_UP;
    int increment = servoPos == SERVO_UP ? 1 : -1; 
    for(int i = startPos; i != endPos; i += increment){
      servo.write(i);
      delay(5);
    }
    
    updateServo = false;
  }
  stepperX.run();
  stepperY.run();
  
}
