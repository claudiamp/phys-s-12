#pragma once
#include <Arduino.h>
#include <MD_MAX72xx.h>

#define HARDWARE_TYPE MD_MAX72XX::PAROLA_HW
#define MAX_DEVICES 2

class Eyes {
  private:
    MD_MAX72XX _mx;

    unsigned long _lastUpdate;
    unsigned long _wakeTime;
    unsigned long _sleepTimeout;
    unsigned long _interval;
    int _frame;
    unsigned int _expression;
    unsigned int _prevExpression;

    byte _openEye[8] = {
      0b00111100,
      0b01000010,
      0b10000001,
      0b10000001,
      0b10000001,
      0b10000001,
      0b01000010,
      0b00111100
    };

    byte _closed[8] = {
      0b00000000,
      0b00000000,
      0b00000000,
      0b01111110,
      0b01111110,
      0b00000000,
      0b00000000,
      0b00000000
    };

    byte _happy[8] = {
      0b00000000,
      0b00000000,
      0b00000000,
      0b10000001,
      0b01000010,
      0b00100100,
      0b00011000,
      0b00000000
    };

    byte _lookDot[8] = {
      0b00000000,
      0b00000000,
      0b00000000,
      0b00011000,
      0b00011000,
      0b00000000,
      0b00000000,
      0b00000000
    };

    byte _xMark[8] = {
      0b10000001,
      0b01000010,
      0b00100100,
      0b00011000,
      0b00011000,
      0b00100100,
      0b01000010,
      0b10000001
    };

    byte _letterZ[8] = {
      0b00000000,
      0b01111110,
      0b01000000,
      0b00100000,
      0b00010000,
      0b00001000,
      0b00000100,
      0b01111110
    };

    void drawEye(int module, byte bmp[8]) {
      for (int r = 0; r < 8; r++) _mx.setRow(module, r, bmp[r]);
    }

    void both(byte bmp[8]) {
      drawEye(0, bmp);
      drawEye(1, bmp);
    }

    // Draws the current frame for the current expression and sets the next
    // interval. Shared by update() (on a timer) and setExpression() (instantly).
    void renderFrame() {
      switch (_expression) {
        case OFF:
          _mx.clear();
          _interval = 1000;
          break;

        case OPEN:
          if (_frame == 0) {
            both(_openEye);
            _interval = 2000;
          } else {
            both(_closed);
            _interval = 150;
          }
          _frame = (_frame + 1) % 2;
          break;

        case HAPPY:
          both(_happy);
          _interval = 500;
          break;

        case THINKING:
          if (_frame == 0) {
            drawEye(0, _openEye); drawEye(1, _lookDot);
            _interval = 400;
          } else {
            drawEye(0, _lookDot); drawEye(1, _openEye);
            _interval = 400;
          }
          _frame = (_frame + 1) % 2;
          break;

        case ERROR:
          if (_frame == 0) {
            both(_xMark);
            _interval = 500;
          } else {
            _mx.clear();
            _interval = 500;
          }
          _frame = (_frame + 1) % 2;
          break;

        case SLEEPING:
          if (_frame == 0) {
            both(_closed);
            _interval = 800;
          } else {
            both(_letterZ);
            _interval = 900;
          }
          _frame = (_frame + 1) % 2;
          break;
      }
    }

  public:
    static const int OFF = 0;
    static const int OPEN = 1;
    static const int HAPPY = 2;
    static const int SLEEPING = 3;
    static const int THINKING = 4;
    static const int ERROR = 5;

    Eyes(int dataPin, int clkPin, int csPin)
      : _mx(HARDWARE_TYPE, dataPin, clkPin, csPin, MAX_DEVICES) {
      _frame = 0;
      _interval = 2000;
      _lastUpdate = 0;
      _expression = OFF;
      _prevExpression = 255;
      _wakeTime = 0;
      _sleepTimeout = 0;
    }

    void begin() {
      _mx.begin();
      _mx.control(MD_MAX72XX::INTENSITY, 4);
      _mx.clear();
    }

    void setSleepTimeout(unsigned long timeout) {
      _sleepTimeout = timeout;
    }

    void setExpression(unsigned int expr) {
      if (expr == _expression) return;
      _expression = expr;
      _prevExpression = expr;
      _frame = 0;
      _lastUpdate = millis();
      if (expr != OFF && expr != SLEEPING && expr != ERROR) {
        _wakeTime = millis();
      }
      renderFrame();   // draw the first frame NOW, so the face shows immediately
    }

    void update() {
      if (_wakeTime > 0 && _expression != ERROR && _expression != THINKING) {
        unsigned long elapsed = millis() - _wakeTime;
        if (elapsed >= _sleepTimeout && elapsed < _sleepTimeout + 3000) {
          setExpression(SLEEPING);
        } else if (elapsed >= _sleepTimeout + 3000) {
          setExpression(OFF);
          _wakeTime = 0;
        }
      }

      if (millis() - _lastUpdate < _interval) return;
      _lastUpdate = millis();

      renderFrame();
    }
};
