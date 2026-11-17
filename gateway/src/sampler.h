// sampler.h — sensorTask: every 500 ms build one raw row (same columns as Flame's dataset), feed
// the predictor, and every 10 s window run the closed loop + produce one Reading for the cloud.
#pragma once
#include <Arduino.h>

void sampler_init();
void sensorTask(void* arg);
