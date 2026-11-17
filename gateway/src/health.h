// health.h — device health for devices/{id}/health + reboot counter in NVS.
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

void        health_init();                  // reboots++ in Preferences (NVS), capture reset reason
uint32_t    health_reboots();
const char* health_reset_reason();
void        health_count_reconnect();
uint32_t    health_reconnects();

void health_build_gateway(JsonDocument& doc, uint32_t now_ts);
// returns false if the node has been silent > NODE_OFFLINE_MS (online:false)
bool health_build_node(JsonDocument& doc, uint32_t now_ts);
// diagnostics that are NOT in the schema (channel, PDR, rx/lost/dup, override...) -> Serial only
void health_print_serial();
