// actuator.h — servo that presses the wall light switch, verified by the LDR (closed loop).
#pragma once
#include <Arduino.h>

enum CtrlSource : uint8_t { SRC_AUTO = 0, SRC_MANUAL = 1 };
enum CtrlAction : uint8_t { ACT_SET_LIGHT = 0, ACT_SERVO_STOP = 1 };

struct ActuatorCmd {
  uint8_t  source;        // CtrlSource
  uint8_t  action;        // CtrlAction
  bool     want_on;       // for ACT_SET_LIGHT
  uint32_t t_detect_ms;   // millis() of first person row after an empty room (0 = unknown)
  char     by[32];        // who sent a manual command
};

void actuator_init();                                     // pins, STOP interrupt, queue
void actuatorTask(void* arg);
void actuator_request_auto(bool want_on, uint32_t t_detect_ms);
// false = actuator queue full -> do NOT mark the command done, retry on the next poll
bool actuator_request_manual(CtrlAction action, bool want_on, const char* by);
bool actuator_stop_latched();                             // STOP button latch (auto disabled)
bool actuator_override_active();                          // manual command within MANUAL_OVERRIDE_MIN
