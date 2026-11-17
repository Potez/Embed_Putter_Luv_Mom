// packets.h — ESP-NOW wire format shared by Node (Pat), ESP32-CAM (Flame) and Gateway (Jeen).
//
// Rules (see firmware/PROTOCOL.md):
//   * every struct is packed, little-endian (all ESP32s), first byte = packet_type
//   * Node sends NodePacket every 500 ms (2 Hz); CAM sends CamPacket on every count (~3 Hz)
//   * Gateway answers every valid packet with an AckPacket (same seq) to the sender MAC
//   * Sender waits 300 ms for the ACK, retries up to 3 times with the SAME seq
//   * seq starts at 0 or 1 after boot and increments by 1 per NEW packet (not per retry)
//   * timestamps = Unix seconds from NTP; send 0 if the clock is not synced yet
//
// Change this file only together with the whole team — sizes are checked below.
#pragma once
#include <stdint.h>

#define ROOMSENSE_PROTOCOL_VERSION 1

enum PacketType : uint8_t {
  PKT_NODE = 1,
  PKT_CAM  = 2,
  PKT_ACK  = 3,
};

// Node (ESP32-WROOM, Pat): HC-SR501 PIR, E18-D80NK door IR, KY-037 sound, IR flame. Every 500 ms.
struct __attribute__((packed)) NodePacket {
  uint8_t  packet_type;  // = PKT_NODE
  uint8_t  node_id;      // 1 = node-A, 2 = node-B, ...
  uint32_t node_seq;     // +1 per new packet, restarts after reboot
  uint32_t node_ts;      // Unix seconds (NTP), 0 = not synced
  uint8_t  door_do;      // ACTIVE-LOW: 0 = E18 saw an object AT LEAST ONCE during the last 500 ms (latched)
  uint8_t  pir;          // 1 = motion
  int16_t  people_ir;    // count from the door counter, -1 = not supported
  uint16_t sound_raw;    // KY-037 analog ADC value (0..4095), peak over the last 500 ms preferred
  uint8_t  flame_do;     // ACTIVE-LOW: 0 = flame detected
};

// ESP32-CAM (Flame): person counter. Sent every time a count is produced (~3 Hz).
struct __attribute__((packed)) CamPacket {
  uint8_t  packet_type;  // = PKT_CAM
  uint8_t  cam_id;       // 1 = cam-A, ...
  uint32_t seq;          // +1 per new packet, restarts after reboot
  uint32_t ts;           // Unix seconds (NTP), 0 = not synced
  int8_t   person_count; // number of people, -1 = could not count
  uint8_t  ai_conf;      // 0..100 (gateway converts to 0..1 for the cloud)
};

// Gateway -> sender acknowledgement.
struct __attribute__((packed)) AckPacket {
  uint8_t  packet_type;  // = PKT_ACK
  uint8_t  src_type;     // PacketType being acknowledged (PKT_NODE / PKT_CAM)
  uint8_t  src_id;       // node_id or cam_id being acknowledged
  uint32_t seq;          // seq being acknowledged
};

static_assert(sizeof(NodePacket) == 17, "NodePacket must be 17 bytes");
static_assert(sizeof(CamPacket)  == 12, "CamPacket must be 12 bytes");
static_assert(sizeof(AckPacket)  == 7,  "AckPacket must be 7 bytes");

// ESP-NOW timing contract
#define ESPNOW_ACK_TIMEOUT_MS 300
#define ESPNOW_MAX_RETRIES    3
