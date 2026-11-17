// sensors.h — gateway-local sensors: DHT11 (temp/humidity) and KY-018 LDR (light confirmation).
// NOTE: these values are uploaded but are NEVER fed to the model (Flame: LDR = label leakage).
#pragma once
#include <Arduino.h>
#include "config.h"

void     sensors_init();
void     sensors_poll();              // call every sample; reads DHT11 at most every 2 s
float    sensors_temp_c();            // NAN if no valid read yet
float    sensors_humidity();          // NAN if no valid read yet
uint16_t sensors_read_ldr();          // fresh averaged read, normalised so that HIGHER = brighter
bool     sensors_light_on();          // fresh LDR read > LDR_ON_THRESHOLD

// sound: KY-037 raw ADC -> relative level. NOT calibrated dB (see sensors.cpp).
uint8_t  sound_raw_to_db(uint16_t raw);

#if MOCK_SENSORS
void     sensors_mock_press_switch(); // simulated wall switch: every servo press toggles it
bool     sensors_mock_light_state();
#endif
