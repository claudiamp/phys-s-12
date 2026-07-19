#pragma once
#include <Arduino.h>

class TouchPad {
  private:
    uint8_t _pin;
    uint16_t _threshold;
    bool _touching;

  public:
    TouchPad(uint8_t pin, uint16_t threshold = 300) {
      _pin = pin;
      _threshold = threshold;
      _touching = false;
    }

    void begin() {
      // touchRead needs no pinMode
    }

    uint16_t raw() {
      return touchRead(_pin);
    }

    // Rising-edge: true once per touch. Consumes the edge.
    bool touched() {
      bool current = touchRead(_pin) < _threshold;

      if (current && !_touching) {
        _touching = true;
        return true;
      }

      if (!current) {
        _touching = false;
      }

      return false;
    }
};