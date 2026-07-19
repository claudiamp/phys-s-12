#pragma once
#include <Arduino.h>
#include "driver/i2s.h"

// Drives a MAX98357A I2S amplifier.
// Plays 16-bit signed PCM clips (mono) embedded in flash — see audio_data.h.
//
// Optional: pass sdPin to control the amp's SD (shutdown) pin. When set, the
// amp is muted except during playback, which removes idle hiss and the little
// bursts of interference the WiFi radio injects between clips.
// Wire the amp's SD pin to that GPIO and nothing else.
class Speaker {
  private:
    int _bclkPin;
    int _lrcPin;
    int _doutPin;
    int _sdPin;
    uint32_t _sampleRate;
    i2s_port_t _port;
    float _volume;   // 0.0 (silent) .. 1.0 (full)

  public:
    Speaker(int bclkPin, int lrcPin, int doutPin,
            uint32_t sampleRate = 16000, int sdPin = -1,
            i2s_port_t port = I2S_NUM_0) {
      _bclkPin = bclkPin;
      _lrcPin = lrcPin;
      _doutPin = doutPin;
      _sdPin = sdPin;
      _sampleRate = sampleRate;
      _port = port;
      _volume = 0.6f;
    }

    void begin() {
      if (_sdPin >= 0) {
        pinMode(_sdPin, OUTPUT);
        digitalWrite(_sdPin, LOW);   // start muted
      }

      i2s_config_t cfg = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = _sampleRate,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 512,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0
      };
      i2s_driver_install(_port, &cfg, 0, NULL);

      i2s_pin_config_t pins = {
        .mck_io_num = I2S_PIN_NO_CHANGE,
        .bck_io_num = _bclkPin,
        .ws_io_num = _lrcPin,
        .data_out_num = _doutPin,
        .data_in_num = I2S_PIN_NO_CHANGE
      };
      i2s_set_pin(_port, &pins);
      i2s_zero_dma_buffer(_port);
    }

    // 0.0 = silent, 1.0 = full scale.
    void setVolume(float v) {
      if (v < 0.0f) v = 0.0f;
      if (v > 1.0f) v = 1.0f;
      _volume = v;
    }

    // Blocking: unmutes the amp, plays the clip (with a short fade in/out to
    // avoid start/stop pops), then mutes again.
    void play(const int16_t* data, uint32_t numSamples) {
      if (_sdPin >= 0) {
        digitalWrite(_sdPin, HIGH);
        delay(5);
      }

      // ~8 ms fade at each end kills the click when the amp powers up/down.
      uint32_t fade = _sampleRate / 125;
      if (fade > numSamples / 2) fade = numSamples / 2;

      const size_t CHUNK = 512;
      int16_t buf[CHUNK];
      size_t bytesWritten;
      uint32_t i = 0;
      while (i < numSamples) {
        size_t n = (numSamples - i < CHUNK) ? (numSamples - i) : CHUNK;
        for (size_t j = 0; j < n; j++) {
          uint32_t idx = i + j;
          float g = _volume;
          if (fade > 0) {
            if (idx < fade) {
              g *= (float)idx / fade;                       // fade in
            } else if (idx >= numSamples - fade) {
              g *= (float)(numSamples - idx) / fade;        // fade out
            }
          }
          buf[j] = (int16_t)(data[idx] * g);
        }
        i2s_write(_port, buf, n * sizeof(int16_t), &bytesWritten, portMAX_DELAY);
        i += n;
      }
      i2s_zero_dma_buffer(_port);

      if (_sdPin >= 0) {
        delay(5);                     // let the last samples flush out
        digitalWrite(_sdPin, LOW);    // mute amp again -> no idle hiss/interference
      }
    }
};
