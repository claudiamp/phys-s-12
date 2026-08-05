#pragma once
#include <Arduino.h>

class TouchPad {
  private:
    uint8_t  _pin;
    uint32_t _baseline;   // idle level, slowly re-learned while released
    uint8_t  _pct;        // touch when the reading sits _pct% above baseline
    bool     _touching;

    // Halfway back down to baseline — releases cleanly without chattering.
    uint32_t releaseLevel() { return (_baseline + threshold()) / 2; }

  public:
    // Through a wood panel the swing is small — idle ~31.8k, touched ~42k, so
    // roughly +32%. 15% sits between idle noise and a real touch with margin
    // on both sides. Raise it if it self-triggers, lower it if it misses taps.
    TouchPad(uint8_t pin, uint8_t pct = 15) {
      _pin = pin;
      _pct = pct;
      _baseline = 0;
      _touching = false;
    }

    // IMPORTANT: don't touch the foil during begin() — this learns the baseline.
    void begin() {
      // The touch peripheral reads high and erratic for the first ~150ms after
      // boot. Averaging those in is what wrecks the baseline, so throw them out.
      for (uint8_t i = 0; i < 16; i++) { touchRead(_pin); delay(10); }

      // Idle is the *floor* of the readings, never the average: noise and any
      // stray proximity only ever push the value up, so the minimum is truth.
      _baseline = touchRead(_pin);
      for (uint8_t i = 0; i < 48; i++) {
        uint32_t r = touchRead(_pin);
        if (r < _baseline) _baseline = r;
        delay(5);
      }
    }

    uint32_t raw()       { return touchRead(_pin); }
    uint32_t baseline()  { return _baseline; }
    uint32_t threshold() { return _baseline + (_baseline * _pct) / 100; }

    // Rising edge: true once per touch. Consumes the edge.
    bool touched() {
      uint32_t r = touchRead(_pin);
      bool current = _touching ? (r > releaseLevel()) : (r > threshold());

      // Creep the baseline toward the idle level, one count at a time, and
      // ONLY while released — so humidity and temperature drift in the wood
      // can't slowly walk us past the threshold, but a held touch can't
      // teach the baseline that "touched" is the new normal either.
      if (!current) {
        if (r > _baseline) _baseline++;
        else if (r < _baseline) _baseline--;
      }

      if (current && !_touching) { _touching = true; return true; }
      if (!current) _touching = false;
      return false;
    }
};
