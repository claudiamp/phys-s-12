/*
Code updated by Bobby McCarthy 4/19/2026
Intended for Xiao Esp32c3

Using Libraries: 
- Async TCP 3.4.10 https://github.com/ESP32Async/AsyncTCP
- ESP Async WebServer 3.10.3 https://github.com/ESP32Async/ESPAsyncWebServer
- AccelStepper 1.64 https://www.airspayce.com/mikem/arduino/AccelStepper/
- ESP32Servo 3.13 https://github.com/madhephaestus/ESP32Servo

How To Use:
  - Connect to esp-captive under wifi networks on your laptop
  - Then go to 192.168.4.1 in your browser
*/


#include <AsyncTCP.h>
#include <WiFi.h>

#include <ESPAsyncWebServer.h>
#include "html.h"

#include <AccelStepper.h>
#include <ESP32Servo.h>

const int xLimit = D8;
const int yLimit = D7;

const int stepPinX = D1;
const int dirPinX = D5;
const int stepPinY = D3;
const int dirPinY = D2;
float pulleyDiamY = 18.7;
float pulleyDiamX = 12.22;
const float xMicrosteps = 0.75;
const float yMicrosteps = 0.75;
const int stepsPerRev = 200;

const float xMmtoSteps = (xMicrosteps*stepsPerRev)/(pulleyDiamX*PI);
const float yMmtoSteps = (yMicrosteps*stepsPerRev)/(pulleyDiamY*PI);

const int MAX_X_DIST = 457; //mm
const int MAX_X_STEPS = MAX_X_DIST * xMmtoSteps;


const int servoPin = D4;
const int SERVO_DOWN = 0;
const int SERVO_UP = 140;
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
const float CIRCLE_CX = 10.0;   // mm from home corner
const float CIRCLE_CY = 10.0;
const float CIRCLE_R  = 5.0;
const int   CIRCLE_SEGMENTS = 24;
const float DOT_R = 0.8;        // the dot in the middle
const int   DOT_SEGMENTS = 8;
const float DRAW_SPEED = 250;
const float DRAW_ACCEL = 400;
volatile bool drawCircle = false;

// blocking move, both axes scaled so they arrive together
void moveToMm(float xmm, float ymm) {
  long tx = lroundf(xmm * xMmtoSteps);
  long ty = lroundf(ymm * yMmtoSteps);
  tx = constrain(tx, 0L, (long)MAX_X_STEPS);   // same guard as the websocket path
  if (ty < 0) ty = 0;
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

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);
  WiFi.softAP("esp-captive claudia's team");
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
  stepperY.setAcceleration(1000);
  stepperY.setMaxSpeed(2000);

  servo.setPeriodHertz(50);    // standard 50 hz servo
	servo.attach(servoPin, 1000, 2000);
  // stepperX.moveTo(3200);
  // stepperY.moveTo(100);

  // serves root html page
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", (const uint8_t *)htmlContent, sizeof(htmlContent)/ sizeof(htmlContent[0]));
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
    targetXPosSteps = constrain(targetXPosSteps, 0, MAX_X_STEPS);
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
  }

  if(drawCircle){
    drawCircle = false;
    ring(CIRCLE_CX, CIRCLE_CY, CIRCLE_R, CIRCLE_SEGMENTS);
    ring(CIRCLE_CX, CIRCLE_CY, DOT_R, DOT_SEGMENTS);
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
