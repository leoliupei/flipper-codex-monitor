#include <furi.h>
#include <gui/gui.h>
#include <input/input.h>
#include <cli/cli.h>
#include <notification/notification.h>
#include <notification/notification_messages.h>
#include <bt/bt_service/bt.h>
#include <profiles/serial_profile.h>
#include <services/battery_service.h>
#include <services/dev_info_service.h>
#include <services/serial_service.h>
#include <furi_hal_bt.h>
#include <furi_hal_power.h>
#include <furi_hal_rtc.h>
#include <furi_hal_version.h>
#include <datetime/datetime.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef enum {
    CodexActivityIdle,
    CodexActivityWorking,
    CodexActivityDone,
} CodexActivity;

typedef enum {
    CodexLinkNone,
    CodexLinkUsb,
    CodexLinkBle,
} CodexLink;

typedef enum {
    CodexPageHome,
    CodexPageQuota,
    CodexPageUsage,
    CodexPageTasks,
    CodexPageLink,
} CodexPage;

typedef enum {
    CodexUsageDaily,
    CodexUsageWeekly,
    CodexUsageTotal,
} CodexUsageView;

typedef enum {
    CodexTasksOverview,
    CodexTaskLive,
    CodexTaskTokens,
} CodexTasksView;

#define CODEX_BLE_PACKET_MAX         191
#define CODEX_BLE_ACTION_OPEN_CHATGPT "ACT OPEN\n"
#define CODEX_LOOP_INTERVAL_MS       125
#define CODEX_USB_LOW_SAMPLES        2
#define CODEX_USB_DISCONNECT_VOLTAGE 2.0f
#define CODEX_LED_PHASES             80
#define CODEX_BLE_MARKER             "CODEXMON1"
#define CODEX_BATTERY_INTERVAL_MS    5000
#define CODEX_ACTIVITY_INTERVAL_MS   125
#define CODEX_DONE_ANIMATION_FRAMES  16
#define CODEX_USAGE_DAYS             30
#define CODEX_TASK_SLOTS              16
#define CODEX_TASK_LABEL_MAX          7

typedef struct {
    uint16_t size;
    char data[CODEX_BLE_PACKET_MAX + 1];
} CodexBlePacket;

typedef enum {
    CodexEventInput,
    CodexEventBtStatus,
    CodexEventBleData,
} CodexEventType;

typedef struct {
    CodexEventType type;
    union {
        InputEvent input;
        BtStatus bt_status;
        CodexBlePacket ble_packet;
    } data;
} CodexEvent;

typedef struct {
    bool valid;
    bool token_available;
    bool is_side;
    uint8_t number;
    char label[CODEX_TASK_LABEL_MAX + 1];
    CodexActivity activity;
    uint32_t started_at;
    uint32_t updated_at;
    uint64_t total_tokens;
    uint64_t last_tokens;
    uint64_t last_input_tokens;
    uint64_t input_tokens;
    uint64_t cached_input_tokens;
    uint64_t output_tokens;
    uint64_t reasoning_output_tokens;
    uint32_t context_window;
} CodexTaskModel;

typedef struct {
    bool connected;
    bool ble_advertising;
    bool ble_connected;
    CodexLink link;
    int32_t quota_remaining;
    uint32_t duration_minutes;
    uint32_t resets_at;
    int8_t reset_hour;
    int8_t reset_minute;
    uint8_t reset_credits;
    uint8_t active_turns;
    char plan;
    CodexActivity activity;
    uint8_t animation_frame;
    uint8_t battery_percent;
    uint32_t activity_since;
    uint32_t last_completed_at;
    uint32_t completion_sequence;
    uint32_t quota_fetched_at;
    uint8_t health_flags;
    int32_t utc_offset_seconds;
    uint64_t lifetime_tokens;
    uint64_t peak_daily_tokens;
    uint32_t longest_running_turn_sec;
    uint16_t current_streak_days;
    uint16_t longest_streak_days;
    uint32_t usage_fetched_at;
    uint32_t usage_latest_date;
    uint32_t daily_millions[CODEX_USAGE_DAYS];
    bool usage_available;
    CodexTaskModel tasks[CODEX_TASK_SLOTS];
    uint8_t task_count;
    uint32_t last_payload_at;
    uint32_t link_since;
} CodexMonitorModel;

typedef struct {
    CodexMonitorModel model;
    FuriMutex* mutex;
    FuriMessageQueue* event_queue;
    ViewPort* view_port;
    NotificationApp* notifications;
    Bt* bt;
    FuriHalBleProfileBase* ble_profile;
    uint8_t led_phase;
    uint8_t usb_low_samples;
    uint32_t last_led_tick;
    uint32_t last_animation_tick;
    uint32_t last_battery_tick;
    CodexPage page;
    CodexUsageView usage_view;
    uint8_t usage_range_days;
    CodexTasksView tasks_view;
    uint8_t selected_task;
    uint8_t selected_task_number;
    bool back_press_started_on_home;
    bool completion_sequence_known;
} CodexMonitorApp;

typedef struct {
    FuriHalBleProfileBase base;
    BleServiceDevInfo* dev_info;
    BleServiceBattery* battery;
    BleServiceSerial* serial;
} CodexBleProfile;

static const FuriHalBleProfileTemplate codex_ble_profile_template;

static FuriHalBleProfileBase* codex_ble_profile_start(FuriHalBleProfileParams params) {
    (void)params;
    CodexBleProfile* profile = malloc(sizeof(CodexBleProfile));
    furi_check(profile);
    profile->base.config = &codex_ble_profile_template;
    profile->dev_info = ble_svc_dev_info_start();
    profile->battery = ble_svc_battery_start(true);
    profile->serial = ble_svc_serial_start();
    return &profile->base;
}

static void codex_ble_profile_stop(FuriHalBleProfileBase* base) {
    furi_check(base && base->config == &codex_ble_profile_template);
    CodexBleProfile* profile = (CodexBleProfile*)base;
    ble_svc_battery_stop(profile->battery);
    ble_svc_dev_info_stop(profile->dev_info);
    ble_svc_serial_stop(profile->serial);
    free(profile);
}

static void codex_ble_profile_get_config(GapConfig* config, FuriHalBleProfileParams params) {
    ble_profile_serial->get_gap_config(config, params);
    const uint8_t marker[] = CODEX_BLE_MARKER;
    memcpy(config->mfg_data, marker, sizeof(marker) - 1);
    config->mfg_data_len = sizeof(marker) - 1;
    snprintf(
        config->adv_name + 1,
        sizeof(config->adv_name) - 1,
        "Codex %s",
        furi_hal_version_get_name_ptr());
}

static const FuriHalBleProfileTemplate codex_ble_profile_template = {
    .start = codex_ble_profile_start,
    .stop = codex_ble_profile_stop,
    .get_gap_config = codex_ble_profile_get_config,
};

static CodexBleProfile* codex_ble_profile_cast(FuriHalBleProfileBase* base) {
    furi_check(base && base->config == &codex_ble_profile_template);
    return (CodexBleProfile*)base;
}

static void codex_ble_profile_set_callback(
    FuriHalBleProfileBase* base,
    uint16_t buffer_size,
    SerialServiceEventCallback callback,
    void* context) {
    CodexBleProfile* profile = codex_ble_profile_cast(base);
    ble_svc_serial_set_callbacks(profile->serial, buffer_size, callback, context);
}

static bool codex_ble_profile_tx(FuriHalBleProfileBase* base, uint8_t* data, uint16_t size) {
    CodexBleProfile* profile = codex_ble_profile_cast(base);
    return ble_svc_serial_update_tx(profile->serial, data, size);
}

static bool codex_monitor_open_chatgpt(CodexMonitorApp* app) {
    if(!app->ble_profile) return false;
    uint8_t action[] = CODEX_BLE_ACTION_OPEN_CHATGPT;
    return codex_ble_profile_tx(app->ble_profile, action, sizeof(action) - 1);
}

static void codex_monitor_set_rgb(CodexMonitorApp* app, uint8_t red, uint8_t green, uint8_t blue) {
    const NotificationMessage red_message = {
        .type = NotificationMessageTypeLedRed,
        .data.led.value = red,
    };
    const NotificationMessage green_message = {
        .type = NotificationMessageTypeLedGreen,
        .data.led.value = green,
    };
    const NotificationMessage blue_message = {
        .type = NotificationMessageTypeLedBlue,
        .data.led.value = blue,
    };
    const NotificationSequence sequence = {
        &red_message,
        &green_message,
        &blue_message,
        &message_do_not_reset,
        NULL,
    };
    notification_message_block(app->notifications, &sequence);
}

static uint8_t codex_monitor_led_lerp(uint8_t start, uint8_t end, uint8_t step, uint8_t span) {
    uint32_t progress = ((uint32_t)step * 256U) / span;
    uint32_t eased = (progress * progress * (768U - 2U * progress)) >> 16;
    int32_t delta = (int32_t)end - start;
    return (uint8_t)((int32_t)start + (delta * (int32_t)eased) / 256);
}

static void codex_monitor_working_led(CodexMonitorApp* app, uint8_t phase) {
    static const uint8_t colors[][3] = {
        {0, 48, 220},
        {0, 120, 152},
        {96, 32, 192},
    };
    uint8_t from;
    uint8_t to;
    uint8_t step;
    uint8_t span;

    phase %= CODEX_LED_PHASES;
    if(phase < 27) {
        from = 0;
        to = 1;
        step = phase;
        span = 27;
    } else if(phase < 54) {
        from = 1;
        to = 2;
        step = phase - 27;
        span = 27;
    } else {
        from = 2;
        to = 0;
        step = phase - 54;
        span = 26;
    }

    codex_monitor_set_rgb(
        app,
        codex_monitor_led_lerp(colors[from][0], colors[to][0], step, span),
        codex_monitor_led_lerp(colors[from][1], colors[to][1], step, span),
        codex_monitor_led_lerp(colors[from][2], colors[to][2], step, span));
}

static void codex_monitor_led_off(CodexMonitorApp* app) {
    notification_message(app->notifications, &sequence_reset_rgb);
}

static const char* codex_link_name(const CodexMonitorModel* model) {
    if(model->link == CodexLinkUsb) return "USB";
    if(model->link == CodexLinkBle) return "BLE";
    if(model->ble_connected) return "BLE?";
    if(model->ble_advertising) return "PAIR";
    return "WAIT";
}

#define CODEX_GLYPH(a, b, c, d, e)                                                                \
    (((uint16_t)(a) << 12) | ((uint16_t)(b) << 9) | ((uint16_t)(c) << 6) | ((uint16_t)(d) << 3) | \
     (uint16_t)(e))

static uint16_t codex_compact_glyph(char character) {
    switch(character) {
    case '0':
        return CODEX_GLYPH(7, 5, 5, 5, 7);
    case '1':
        return CODEX_GLYPH(2, 6, 2, 2, 7);
    case '2':
        return CODEX_GLYPH(7, 1, 7, 4, 7);
    case '3':
        return CODEX_GLYPH(7, 1, 7, 1, 7);
    case '4':
        return CODEX_GLYPH(5, 5, 7, 1, 1);
    case '5':
        return CODEX_GLYPH(7, 4, 7, 1, 7);
    case '6':
        return CODEX_GLYPH(7, 4, 7, 5, 7);
    case '7':
        return CODEX_GLYPH(7, 1, 2, 2, 2);
    case '8':
        return CODEX_GLYPH(7, 5, 7, 5, 7);
    case '9':
        return CODEX_GLYPH(7, 5, 7, 1, 7);
    case 'A':
        return CODEX_GLYPH(2, 5, 7, 5, 5);
    case 'B':
        return CODEX_GLYPH(6, 5, 6, 5, 6);
    case 'C':
        return CODEX_GLYPH(7, 4, 4, 4, 7);
    case 'D':
        return CODEX_GLYPH(6, 5, 5, 5, 6);
    case 'E':
        return CODEX_GLYPH(7, 4, 6, 4, 7);
    case 'F':
        return CODEX_GLYPH(7, 4, 6, 4, 4);
    case 'G':
        return CODEX_GLYPH(7, 4, 5, 5, 7);
    case 'H':
        return CODEX_GLYPH(5, 5, 7, 5, 5);
    case 'I':
        return CODEX_GLYPH(7, 2, 2, 2, 7);
    case 'J':
        return CODEX_GLYPH(1, 1, 1, 5, 7);
    case 'K':
        return CODEX_GLYPH(5, 5, 6, 5, 5);
    case 'L':
        return CODEX_GLYPH(4, 4, 4, 4, 7);
    case 'M':
        return CODEX_GLYPH(5, 7, 7, 5, 5);
    case 'N':
        return CODEX_GLYPH(5, 7, 7, 7, 5);
    case 'O':
        return CODEX_GLYPH(7, 5, 5, 5, 7);
    case 'P':
        return CODEX_GLYPH(6, 5, 6, 4, 4);
    case 'Q':
        return CODEX_GLYPH(7, 5, 5, 7, 1);
    case 'R':
        return CODEX_GLYPH(6, 5, 6, 5, 5);
    case 'S':
        return CODEX_GLYPH(7, 4, 7, 1, 7);
    case 'T':
        return CODEX_GLYPH(7, 2, 2, 2, 2);
    case 'U':
        return CODEX_GLYPH(5, 5, 5, 5, 7);
    case 'V':
        return CODEX_GLYPH(5, 5, 5, 5, 2);
    case 'W':
        return CODEX_GLYPH(5, 5, 7, 7, 5);
    case 'X':
        return CODEX_GLYPH(5, 5, 2, 5, 5);
    case 'Y':
        return CODEX_GLYPH(5, 5, 2, 2, 2);
    case 'Z':
        return CODEX_GLYPH(7, 1, 2, 4, 7);
    case '%':
        return CODEX_GLYPH(5, 1, 2, 4, 5);
    case ':':
        return CODEX_GLYPH(0, 2, 0, 2, 0);
    case '-':
        return CODEX_GLYPH(0, 0, 7, 0, 0);
    case '<':
        return CODEX_GLYPH(1, 2, 4, 2, 1);
    case '>':
        return CODEX_GLYPH(4, 2, 1, 2, 4);
    default:
        return 0;
    }
}

#define CODEX_GLYPH_5X7(a, b, c, d, e, f, g)                                 \
    (((uint64_t)(a) << 30) | ((uint64_t)(b) << 25) | ((uint64_t)(c) << 20) | \
     ((uint64_t)(d) << 15) | ((uint64_t)(e) << 10) | ((uint64_t)(f) << 5) | (uint64_t)(g))

static uint64_t codex_large_glyph(char character) {
    switch(character) {
    case '0':
        return CODEX_GLYPH_5X7(14, 17, 19, 21, 25, 17, 14);
    case '1':
        return CODEX_GLYPH_5X7(4, 12, 4, 4, 4, 4, 14);
    case '2':
        return CODEX_GLYPH_5X7(14, 17, 1, 2, 4, 8, 31);
    case '3':
        return CODEX_GLYPH_5X7(30, 1, 1, 14, 1, 1, 30);
    case '4':
        return CODEX_GLYPH_5X7(2, 6, 10, 18, 31, 2, 2);
    case '5':
        return CODEX_GLYPH_5X7(31, 16, 16, 30, 1, 1, 30);
    case '6':
        return CODEX_GLYPH_5X7(14, 16, 16, 30, 17, 17, 14);
    case '7':
        return CODEX_GLYPH_5X7(31, 1, 2, 4, 8, 8, 8);
    case '8':
        return CODEX_GLYPH_5X7(14, 17, 17, 14, 17, 17, 14);
    case '9':
        return CODEX_GLYPH_5X7(14, 17, 17, 15, 1, 1, 14);
    case 'A':
        return CODEX_GLYPH_5X7(14, 17, 17, 31, 17, 17, 17);
    case 'B':
        return CODEX_GLYPH_5X7(30, 17, 17, 30, 17, 17, 30);
    case 'C':
        return CODEX_GLYPH_5X7(15, 16, 16, 16, 16, 16, 15);
    case 'D':
        return CODEX_GLYPH_5X7(30, 17, 17, 17, 17, 17, 30);
    case 'E':
        return CODEX_GLYPH_5X7(31, 16, 16, 30, 16, 16, 31);
    case 'F':
        return CODEX_GLYPH_5X7(31, 16, 16, 30, 16, 16, 16);
    case 'G':
        return CODEX_GLYPH_5X7(15, 16, 16, 23, 17, 17, 15);
    case 'H':
        return CODEX_GLYPH_5X7(17, 17, 17, 31, 17, 17, 17);
    case 'I':
        return CODEX_GLYPH_5X7(31, 4, 4, 4, 4, 4, 31);
    case 'J':
        return CODEX_GLYPH_5X7(1, 1, 1, 1, 17, 17, 14);
    case 'K':
        return CODEX_GLYPH_5X7(17, 18, 20, 24, 20, 18, 17);
    case 'L':
        return CODEX_GLYPH_5X7(16, 16, 16, 16, 16, 16, 31);
    case 'M':
        return CODEX_GLYPH_5X7(17, 27, 21, 21, 17, 17, 17);
    case 'N':
        return CODEX_GLYPH_5X7(17, 25, 21, 19, 17, 17, 17);
    case 'O':
        return CODEX_GLYPH_5X7(14, 17, 17, 17, 17, 17, 14);
    case 'P':
        return CODEX_GLYPH_5X7(30, 17, 17, 30, 16, 16, 16);
    case 'Q':
        return CODEX_GLYPH_5X7(14, 17, 17, 17, 21, 18, 13);
    case 'R':
        return CODEX_GLYPH_5X7(30, 17, 17, 30, 20, 18, 17);
    case 'S':
        return CODEX_GLYPH_5X7(15, 16, 16, 14, 1, 1, 30);
    case 'T':
        return CODEX_GLYPH_5X7(31, 4, 4, 4, 4, 4, 4);
    case 'U':
        return CODEX_GLYPH_5X7(17, 17, 17, 17, 17, 17, 14);
    case 'V':
        return CODEX_GLYPH_5X7(17, 17, 17, 17, 17, 10, 4);
    case 'W':
        return CODEX_GLYPH_5X7(17, 17, 17, 21, 21, 21, 10);
    case 'X':
        return CODEX_GLYPH_5X7(17, 17, 10, 4, 10, 17, 17);
    case 'Y':
        return CODEX_GLYPH_5X7(17, 17, 10, 4, 4, 4, 4);
    case 'Z':
        return CODEX_GLYPH_5X7(31, 1, 2, 4, 8, 16, 31);
    case '%':
        return CODEX_GLYPH_5X7(25, 26, 4, 8, 19, 3, 0);
    case '-':
        return CODEX_GLYPH_5X7(0, 0, 0, 31, 0, 0, 0);
    case '?':
        return CODEX_GLYPH_5X7(14, 17, 1, 2, 4, 0, 4);
    default:
        return 0;
    }
}

static uint16_t codex_large_width(const char* text, uint8_t scale) {
    size_t length = strlen(text);
    if(length == 0) return 0;
    return (uint16_t)((length * 6 - 1) * scale);
}

static void codex_large_draw(
    Canvas* canvas,
    int32_t x,
    int32_t y,
    Align align,
    uint8_t scale,
    const char* text) {
    uint16_t width = codex_large_width(text, scale);
    if(align == AlignCenter)
        x -= width / 2;
    else if(align == AlignRight)
        x -= width;

    while(*text) {
        uint64_t glyph = codex_large_glyph(*text++);
        for(uint8_t row = 0; row < 7; row++) {
            for(uint8_t column = 0; column < 5; column++) {
                uint8_t bit = (6 - row) * 5 + (4 - column);
                if(glyph & (1ULL << bit)) {
                    canvas_draw_box(canvas, x + column * scale, y + row * scale, scale, scale);
                }
            }
        }
        x += 6 * scale;
    }
}

static uint8_t codex_compact_width(const char* text) {
    size_t length = strlen(text);
    if(length == 0) return 0;
    size_t width = length * 4 - 1;
    return width > 255 ? 255 : (uint8_t)width;
}

static void
    codex_compact_draw(Canvas* canvas, int32_t x, int32_t y, Align align, const char* text) {
    uint8_t width = codex_compact_width(text);
    if(align == AlignCenter)
        x -= width / 2;
    else if(align == AlignRight)
        x -= width;

    while(*text) {
        uint16_t glyph = codex_compact_glyph(*text++);
        for(uint8_t row = 0; row < 5; row++) {
            for(uint8_t column = 0; column < 3; column++) {
                uint8_t bit = (4 - row) * 3 + (2 - column);
                if(glyph & (1U << bit)) canvas_draw_dot(canvas, x + column, y + row);
            }
        }
        x += 4;
    }
}

static void codex_monitor_draw_battery(Canvas* canvas, uint8_t percent) {
    if(percent > 100) percent = 100;
    char text[6];
    snprintf(text, sizeof(text), "%u%%", percent);

    canvas_draw_frame(canvas, 93, 2, 14, 7);
    canvas_draw_box(canvas, 107, 4, 2, 3);
    uint8_t fill = (uint8_t)((10U * percent) / 100U);
    if(fill > 0) canvas_draw_box(canvas, 95, 4, fill, 3);
    codex_compact_draw(canvas, 126, 3, AlignRight, text);
}

static const char* codex_activity_name(const CodexMonitorModel* model) {
    if(!model->connected) return "OFFLINE";
    if(model->activity == CodexActivityWorking) return "WORKING";
    if(model->activity == CodexActivityDone) return "DONE";
    return "IDLE";
}

static int8_t codex_monitor_round_rotation(int16_t value) {
    if(value >= 0) return (int8_t)((value + 32) / 64);
    return (int8_t)(-((-value + 32) / 64));
}

static void codex_monitor_rotate_hourglass_point(
    int8_t x,
    int8_t y,
    int8_t cosine,
    int8_t sine,
    int32_t* screen_x,
    int32_t* screen_y) {
    *screen_x = 96 + codex_monitor_round_rotation(x * cosine - y * sine);
    *screen_y = 32 + codex_monitor_round_rotation(x * sine + y * cosine);
}

static void codex_monitor_draw_hourglass_line(
    Canvas* canvas,
    int8_t x0,
    int8_t y0,
    int8_t x1,
    int8_t y1,
    int8_t cosine,
    int8_t sine) {
    int32_t screen_x0;
    int32_t screen_y0;
    int32_t screen_x1;
    int32_t screen_y1;
    codex_monitor_rotate_hourglass_point(
        x0, y0, cosine, sine, &screen_x0, &screen_y0);
    codex_monitor_rotate_hourglass_point(
        x1, y1, cosine, sine, &screen_x1, &screen_y1);
    canvas_draw_line(canvas, screen_x0, screen_y0, screen_x1, screen_y1);
}

static int32_t codex_monitor_animation_lerp(
    int32_t start,
    int32_t end,
    uint8_t step,
    uint8_t span) {
    return start + ((end - start) * step) / span;
}

static void codex_monitor_draw_done_check(Canvas* canvas, uint8_t animation_frame) {
    const uint8_t short_frames = 5;
    uint8_t phase = animation_frame;
    if(phase > CODEX_DONE_ANIMATION_FRAMES) phase = CODEX_DONE_ANIMATION_FRAMES;

    if(phase <= short_frames) {
        int32_t x = codex_monitor_animation_lerp(88, 94, phase, short_frames);
        int32_t y = codex_monitor_animation_lerp(31, 37, phase, short_frames);
        canvas_draw_line(canvas, 88, 31, x, y);
        canvas_draw_line(canvas, 88, 32, x, y + 1);
        return;
    }

    canvas_draw_line(canvas, 88, 31, 94, 37);
    canvas_draw_line(canvas, 88, 32, 94, 38);
    const uint8_t long_phase = phase - short_frames;
    const uint8_t long_frames = CODEX_DONE_ANIMATION_FRAMES - short_frames;
    int32_t x = codex_monitor_animation_lerp(94, 104, long_phase, long_frames);
    int32_t y = codex_monitor_animation_lerp(37, 25, long_phase, long_frames);
    canvas_draw_line(canvas, 94, 37, x, y);
    canvas_draw_line(canvas, 94, 38, x, y + 1);
}

static void codex_monitor_draw_activity(Canvas* canvas, const CodexMonitorModel* model) {
    static const uint8_t idle_chatgpt_icon[54] = {
        0x00, 0x00, 0x00, 0xE0, 0x03, 0x00, 0x30, 0x3E, 0x00, 0x90, 0x43, 0x00,
        0xD8, 0x88, 0x00, 0x5E, 0xBE, 0x00, 0xD2, 0xE7, 0x00, 0xDA, 0x8C, 0x01,
        0x5A, 0x38, 0x01, 0x72, 0x68, 0x01, 0xC6, 0x6C, 0x01, 0x9C, 0x6F, 0x01,
        0xF4, 0xE9, 0x01, 0x44, 0x6C, 0x00, 0x08, 0x27, 0x00, 0xF0, 0x31, 0x00,
        0x00, 0x1F, 0x00, 0x00, 0x00, 0x00,
    };
    if(model->activity == CodexActivityIdle) {
        canvas_draw_xbm(canvas, 87, 23, 18, 18, idle_chatgpt_icon);
        return;
    }
    if(model->activity == CodexActivityDone) {
        codex_monitor_draw_done_check(canvas, model->animation_frame);
        return;
    }
    if(model->activity != CodexActivityWorking) return;

    static const uint8_t flip_frames[8][57] = {
        {0x80, 0x00, 0x00, 0xC0, 0x03, 0x00, 0xC0, 0x1F, 0x00, 0x80, 0x7E, 0x00,
         0x80, 0xF8, 0x01, 0x80, 0xC0, 0x03, 0x00, 0xC1, 0x03, 0x00, 0x61, 0x00,
         0x00, 0x1E, 0x00, 0x00, 0x07, 0x00, 0xC0, 0x03, 0x00, 0xB0, 0x05, 0x00,
         0xFE, 0x07, 0x00, 0xFE, 0x0B, 0x00, 0xFC, 0x0F, 0x00, 0xF0, 0x0F, 0x00,
         0xC0, 0x1F, 0x00, 0x00, 0x1E, 0x00, 0x00, 0x08, 0x00},
        {0x00, 0x06, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x1C, 0x00, 0x00, 0x3E, 0x00,
         0x00, 0x72, 0x00, 0x00, 0xE2, 0x00, 0x00, 0xC2, 0x01, 0x00, 0x82, 0x03,
         0x00, 0x82, 0x07, 0xFB, 0xFF, 0x06, 0xFF, 0x03, 0x00, 0xFE, 0x03, 0x00,
         0xFC, 0x03, 0x00, 0xF8, 0x03, 0x00, 0xF0, 0x03, 0x00, 0xE0, 0x03, 0x00,
         0xC0, 0x01, 0x00, 0x80, 0x03, 0x00, 0x00, 0x03, 0x00},
        {0x00, 0x00, 0x00, 0x00, 0x30, 0x00, 0x00, 0x70, 0x00, 0x00, 0x70, 0x00,
         0x00, 0xF8, 0x00, 0x00, 0xCC, 0x00, 0x02, 0xC4, 0x00, 0x3F, 0xC4, 0x01,
         0xFE, 0x82, 0x01, 0x7E, 0x87, 0x03, 0xFC, 0x1F, 0x03, 0xFC, 0xE1, 0x03,
         0x7C, 0x01, 0x03, 0xF8, 0x00, 0x00, 0xF8, 0x00, 0x00, 0x70, 0x00, 0x00,
         0x70, 0x00, 0x00, 0x60, 0x00, 0x00, 0x00, 0x00, 0x00},
        {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 0x80, 0x00,
         0x0C, 0x80, 0x01, 0x3C, 0xE0, 0x01, 0x5C, 0x90, 0x01, 0xBC, 0x88, 0x01,
         0x7C, 0x85, 0x01, 0xFC, 0x82, 0x01, 0x7C, 0x85, 0x01, 0xBC, 0x88, 0x01,
         0x5C, 0x90, 0x01, 0x3C, 0xE0, 0x01, 0x0C, 0x80, 0x01, 0x08, 0x80, 0x00,
         0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
        {0x00, 0x00, 0x00, 0x60, 0x00, 0x00, 0x70, 0x00, 0x00, 0x70, 0x00, 0x00,
         0xF8, 0x00, 0x00, 0xF8, 0x00, 0x00, 0x7C, 0x01, 0x03, 0xFC, 0xE1, 0x03,
         0xFE, 0x1F, 0x03, 0x7E, 0x87, 0x03, 0xFE, 0x82, 0x01, 0x3F, 0xC4, 0x01,
         0x02, 0xC4, 0x00, 0x00, 0xEC, 0x00, 0x00, 0xF8, 0x00, 0x00, 0x70, 0x00,
         0x00, 0x70, 0x00, 0x00, 0x30, 0x00, 0x00, 0x00, 0x00},
        {0x80, 0x03, 0x00, 0xC0, 0x03, 0x00, 0xE0, 0x01, 0x00, 0xF0, 0x03, 0x00,
         0xF8, 0x03, 0x00, 0xFC, 0x03, 0x00, 0xFE, 0x03, 0x00, 0xFF, 0x03, 0x00,
         0xFF, 0x03, 0x00, 0xFB, 0xFF, 0x02, 0x00, 0x82, 0x03, 0x00, 0x82, 0x03,
         0x00, 0xC2, 0x01, 0x00, 0xE2, 0x00, 0x00, 0x72, 0x00, 0x00, 0x3E, 0x00,
         0x00, 0x1C, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x06, 0x00},
        {0x00, 0x08, 0x00, 0x00, 0x1F, 0x00, 0xC0, 0x0F, 0x00, 0xF0, 0x0F, 0x00,
         0xFC, 0x0F, 0x00, 0xFE, 0x0F, 0x00, 0xFA, 0x07, 0x00, 0xB0, 0x05, 0x00,
         0xC0, 0x03, 0x00, 0x00, 0x07, 0x00, 0x00, 0x39, 0x00, 0x00, 0x61, 0x00,
         0x00, 0xC1, 0x03, 0x80, 0xE0, 0x01, 0x80, 0xF8, 0x01, 0x80, 0x7E, 0x00,
         0xC0, 0x0F, 0x00, 0xC0, 0x03, 0x00, 0x00, 0x00, 0x00},
        {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0x7F, 0x00, 0xF8, 0xFF, 0x00,
         0xE0, 0x3F, 0x00, 0xA0, 0x2F, 0x00, 0x40, 0x17, 0x00, 0x80, 0x0A, 0x00,
         0x00, 0x05, 0x00, 0x00, 0x02, 0x00, 0x00, 0x05, 0x00, 0x80, 0x08, 0x00,
         0x40, 0x10, 0x00, 0x20, 0x20, 0x00, 0x20, 0x20, 0x00, 0xF8, 0xFF, 0x00,
         0xF0, 0x7F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    };
    static const int8_t lines[12][4] = {
        {-5, -7, 5, -7},
        {-6, -6, 6, -6},
        {-4, -5, -4, -4},
        {-4, -4, 0, 0},
        {4, -5, 4, -4},
        {4, -4, 0, 0},
        {0, 0, -4, 4},
        {-4, 4, -4, 5},
        {0, 0, 4, 4},
        {4, 4, 4, 5},
        {-6, 6, 6, 6},
        {-5, 7, 5, 7},
    };
    const uint8_t phase = model->animation_frame % 28;
    if(phase >= 20) {
        canvas_draw_xbm(canvas, 87, 23, 19, 19, flip_frames[phase - 20]);
        return;
    }
    for(uint8_t index = 0; index < 12; index++) {
        codex_monitor_draw_hourglass_line(
            canvas,
            lines[index][0],
            lines[index][1],
            lines[index][2],
            lines[index][3],
            64,
            0);
    }

    const uint8_t sand_stage = phase < 20 ? (phase * 5) / 20 : 4;
    if(phase < 20) {
        for(int8_t y = -5 + sand_stage; y <= -2; y++) {
            const int8_t half_width = -y - 2;
            codex_monitor_draw_hourglass_line(
                canvas, -half_width, y, half_width, y, 64, 0);
        }
    }
    for(uint8_t layer = 0; layer < sand_stage; layer++) {
        const int8_t y = 5 - layer;
        const int8_t half_width = sand_stage - layer - 1;
        codex_monitor_draw_hourglass_line(
            canvas,
            -half_width,
            y,
            half_width,
            y,
            64,
            0);
    }
    if(phase < 16) canvas_draw_dot(canvas, 96, 33 + (phase % 2));
}

static uint32_t codex_monitor_utc_now(const CodexMonitorModel* model) {
    int64_t timestamp = (int64_t)furi_hal_rtc_get_timestamp() - model->utc_offset_seconds;
    if(timestamp < 0) return 0;
    if(timestamp > UINT32_MAX) return UINT32_MAX;
    return (uint32_t)timestamp;
}

static uint8_t codex_monitor_pace_position(const CodexMonitorModel* model) {
    if(model->quota_remaining < 0 || model->duration_minutes == 0 || model->resets_at == 0) {
        return 3;
    }

    int32_t remaining = model->quota_remaining;
    if(remaining > 100) remaining = 100;
    const int32_t used_percent = 100 - remaining;
    const uint64_t duration_seconds = (uint64_t)model->duration_minutes * 60U;
    const uint64_t reset_at = model->resets_at;
    const uint64_t window_start =
        reset_at > duration_seconds ? reset_at - duration_seconds : 0;
    const uint64_t now = codex_monitor_utc_now(model);

    uint64_t elapsed_seconds;
    if(now <= window_start)
        elapsed_seconds = 0;
    else if(now >= reset_at)
        elapsed_seconds = duration_seconds;
    else
        elapsed_seconds = now - window_start;

    const int32_t elapsed_percent =
        (int32_t)((elapsed_seconds * 100U + duration_seconds / 2U) / duration_seconds);
    const int32_t deviation = used_percent - elapsed_percent;

    if(deviation <= -17) return 0;
    if(deviation <= -10) return 1;
    if(deviation <= -4) return 2;
    if(deviation <= 3) return 3;
    if(deviation <= 9) return 4;
    if(deviation <= 16) return 5;
    return 6;
}

static void codex_monitor_draw_pace_meter(Canvas* canvas, const CodexMonitorModel* model) {
    static const uint8_t needle_end[7][2] = {
        {21, 26}, {23, 22}, {27, 19}, {31, 18}, {35, 19}, {39, 22}, {41, 26},
    };

    canvas_draw_circle(canvas, 31, 28, 13);
    canvas_draw_circle(canvas, 31, 28, 12);
    canvas_set_color(canvas, ColorWhite);
    canvas_draw_box(canvas, 17, 29, 29, 21);
    canvas_set_color(canvas, ColorBlack);

    const uint8_t position = codex_monitor_pace_position(model);
    canvas_draw_line(canvas, 31, 28, needle_end[position][0], needle_end[position][1]);
    canvas_draw_disc(canvas, 31, 28, 1);
}

static uint32_t
    codex_monitor_local_timestamp(const CodexMonitorModel* model, uint32_t timestamp) {
    int64_t local = (int64_t)timestamp + model->utc_offset_seconds;
    if(local < 0) return 0;
    if(local > UINT32_MAX) return UINT32_MAX;
    return (uint32_t)local;
}

static void codex_monitor_format_reset_countdown(
    const CodexMonitorModel* model,
    char* text,
    size_t text_size) {
    uint32_t now = codex_monitor_utc_now(model);
    if(model->resets_at == 0) {
        snprintf(text, text_size, "RESET --");
    } else if(model->resets_at <= now) {
        snprintf(text, text_size, "RESET NOW");
    } else {
        uint32_t remaining_seconds = model->resets_at - now;
        if(remaining_seconds > 24U * 60U * 60U) {
            uint32_t days = (remaining_seconds + 24U * 60U * 60U - 1U) / (24U * 60U * 60U);
            snprintf(
                text, text_size, "RESET IN %lu DAY%s", (unsigned long)days, days == 1 ? "" : "S");
        } else {
            uint32_t remaining_minutes = (remaining_seconds + 59U) / 60U;
            uint32_t hours = remaining_minutes / 60U;
            uint32_t minutes = remaining_minutes % 60U;
            snprintf(
                text,
                text_size,
                "RESET IN %02lu:%02lu",
                (unsigned long)hours,
                (unsigned long)minutes);
        }
    }
}

static void codex_monitor_draw_home(Canvas* canvas, const CodexMonitorModel* source) {
    char line[32];
    codex_large_draw(canvas, 2, 2, AlignLeft, 1, "CODEX");
    codex_large_draw(canvas, 76, 2, AlignCenter, 1, codex_link_name(source));
    codex_monitor_draw_battery(canvas, source->battery_percent);
    canvas_draw_line(canvas, 0, 11, 127, 11);

    if(!source->connected) {
        canvas_set_font(canvas, FontPrimary);
        canvas_draw_str_aligned(
            canvas,
            64,
            25,
            AlignCenter,
            AlignCenter,
            source->ble_connected ? "BLE CONNECTED" :
                                   (source->ble_advertising ? "READY FOR BLE" : "NO LINK"));
        canvas_set_font(canvas, FontSecondary);
        canvas_draw_str_aligned(
            canvas,
            64,
            39,
            AlignCenter,
            AlignCenter,
            source->ble_connected ?
                "SYNCING CODEX" :
                (source->ble_advertising ? "WAITING FOR MAC" : "USB / ENABLE BLUETOOTH"));
        canvas_draw_line(canvas, 0, 50, 127, 50);
        canvas_set_font(canvas, FontPrimary);
        canvas_draw_str_aligned(canvas, 64, 62, AlignCenter, AlignBottom, "OFFLINE");
    } else {
        canvas_draw_line(canvas, 63, 12, 63, 50);

        codex_monitor_draw_pace_meter(canvas, source);

        if(source->quota_remaining >= 0) {
            snprintf(line, sizeof(line), "%ld%%", (long)source->quota_remaining);
        } else {
            snprintf(line, sizeof(line), "--%%");
        }
        codex_large_draw(canvas, 31, 33, AlignCenter, 1, line);

        canvas_draw_frame(canvas, 4, 43, 55, 6);
        if(source->quota_remaining > 0) {
            uint8_t fill = (uint8_t)((51U * (uint32_t)source->quota_remaining) / 100U);
            if(fill == 0) fill = 1;
            canvas_draw_box(canvas, 6, 45, fill, 2);
        }

        codex_large_draw(canvas, 96, 13, AlignCenter, 1, codex_activity_name(source));
        codex_monitor_draw_activity(canvas, source);

        if(source->active_turns == 0) {
            snprintf(line, sizeof(line), "0 TASKS");
        } else {
            snprintf(
                line,
                sizeof(line),
                "%u TASK%s",
                source->active_turns,
                source->active_turns == 1 ? "" : "S");
        }
        codex_compact_draw(canvas, 96, 44, AlignCenter, line);

        canvas_draw_line(canvas, 0, 50, 127, 50);
        codex_monitor_format_reset_countdown(source, line, sizeof(line));
        codex_compact_draw(canvas, 2, 55, AlignLeft, line);

        snprintf(
            line,
            sizeof(line),
            "%u RESET%s",
            source->reset_credits,
            source->reset_credits == 1 ? "" : "S");
        codex_compact_draw(canvas, 126, 55, AlignRight, line);
    }
}

static void codex_monitor_draw_secondary_header(
    Canvas* canvas,
    const CodexMonitorModel* model,
    const char* title) {
    canvas_draw_line(canvas, 7, 2, 3, 5);
    canvas_draw_line(canvas, 3, 5, 7, 8);
    canvas_draw_line(canvas, 3, 5, 9, 5);
    codex_large_draw(canvas, 12, 2, AlignLeft, 1, title);
    codex_large_draw(canvas, 76, 2, AlignCenter, 1, codex_link_name(model));
    codex_monitor_draw_battery(canvas, model->battery_percent);
    canvas_draw_line(canvas, 0, 11, 127, 11);
}

static void codex_monitor_format_clock(
    const CodexMonitorModel* model,
    uint32_t timestamp,
    char* text,
    size_t text_size) {
    if(timestamp == 0) {
        snprintf(text, text_size, "--:--");
        return;
    }
    DateTime date_time;
    datetime_timestamp_to_datetime(codex_monitor_local_timestamp(model, timestamp), &date_time);
    snprintf(text, text_size, "%02u:%02u", date_time.hour, date_time.minute);
}

static void codex_monitor_format_month_day(
    const CodexMonitorModel* model,
    uint32_t timestamp,
    char* text,
    size_t text_size) {
    if(timestamp == 0) {
        snprintf(text, text_size, "-- --");
        return;
    }
    DateTime date_time;
    datetime_timestamp_to_datetime(codex_monitor_local_timestamp(model, timestamp), &date_time);
    snprintf(text, text_size, "%02u-%02u", date_time.month, date_time.day);
}

static void codex_monitor_format_date_time(
    const CodexMonitorModel* model,
    uint32_t timestamp,
    char* text,
    size_t text_size) {
    if(timestamp == 0) {
        snprintf(text, text_size, "-- -- --:--");
        return;
    }
    DateTime date_time;
    datetime_timestamp_to_datetime(codex_monitor_local_timestamp(model, timestamp), &date_time);
    snprintf(
        text,
        text_size,
        "%02u-%02u %02u:%02u",
        date_time.month,
        date_time.day,
        date_time.hour,
        date_time.minute);
}

static void codex_monitor_format_link_duration(
    const CodexMonitorModel* model,
    char* text,
    size_t text_size) {
    uint32_t now = furi_hal_rtc_get_timestamp();
    if(!model->connected || model->link == CodexLinkNone || model->link_since == 0 ||
       model->link_since > now) {
        snprintf(text, text_size, "NOT LINKED");
        return;
    }

    uint32_t seconds = now - model->link_since;
    if(seconds < 60) {
        snprintf(
            text,
            text_size,
            "LINKED FOR %lu SECOND%s",
            (unsigned long)seconds,
            seconds == 1 ? "" : "S");
    } else if(seconds < 3600) {
        uint32_t minutes = seconds / 60;
        snprintf(
            text,
            text_size,
            "LINKED FOR %lu MINUTE%s",
            (unsigned long)minutes,
            minutes == 1 ? "" : "S");
    } else if(seconds < 86400) {
        uint32_t hours = seconds / 3600;
        snprintf(
            text, text_size, "LINKED FOR %lu HOUR%s", (unsigned long)hours, hours == 1 ? "" : "S");
    } else {
        uint32_t days = seconds / 86400;
        snprintf(
            text, text_size, "LINKED FOR %lu DAY%s", (unsigned long)days, days == 1 ? "" : "S");
    }
}

static void codex_monitor_format_duration(uint32_t seconds, char* text, size_t text_size) {
    if(seconds >= 86400) {
        uint32_t days = seconds / 86400;
        snprintf(text, text_size, "%lu DAY%s", (unsigned long)days, days == 1 ? "" : "S");
    } else {
        uint32_t hours = seconds / 3600;
        uint32_t minutes = (seconds % 3600) / 60;
        snprintf(text, text_size, "%02lu:%02lu", (unsigned long)hours, (unsigned long)minutes);
    }
}

static void
    codex_monitor_format_reset_short(const CodexMonitorModel* model, char* text, size_t text_size) {
    uint32_t now = codex_monitor_utc_now(model);
    if(model->resets_at == 0) {
        snprintf(text, text_size, "--");
    } else if(model->resets_at <= now) {
        snprintf(text, text_size, "NOW");
    } else {
        uint32_t remaining = model->resets_at - now;
        if(remaining > 86400) {
            uint32_t days = (remaining + 86399) / 86400;
            snprintf(text, text_size, "%lu DAYS", (unsigned long)days);
        } else {
            uint32_t minutes = (remaining + 59) / 60;
            snprintf(
                text,
                text_size,
                "%02lu:%02lu",
                (unsigned long)(minutes / 60),
                (unsigned long)(minutes % 60));
        }
    }
}

static void codex_monitor_draw_offline_page(
    Canvas* canvas,
    const CodexMonitorModel* model,
    const char* title) {
    codex_monitor_draw_secondary_header(canvas, model, title);
    codex_large_draw(canvas, 64, 21, AlignCenter, 1, "OFFLINE");
    codex_compact_draw(
        canvas, 64, 35, AlignCenter, model->ble_connected ? "SYNCING CODEX" : "WAITING FOR LINK");
    canvas_draw_line(canvas, 0, 49, 127, 49);
    codex_compact_draw(canvas, 64, 56, AlignCenter, "BACK TO HOME");
}

static void codex_monitor_draw_quota(Canvas* canvas, const CodexMonitorModel* model) {
    char line[32];
    codex_monitor_draw_secondary_header(canvas, model, "QUOTA");
    canvas_draw_line(canvas, 63, 12, 63, 49);
    codex_compact_draw(canvas, 31, 15, AlignCenter, "LEFT");
    if(model->quota_remaining >= 0)
        snprintf(line, sizeof(line), "%ld%%", (long)model->quota_remaining);
    else
        snprintf(line, sizeof(line), "--%%");
    codex_large_draw(canvas, 31, 23, AlignCenter, 2, line);
    canvas_draw_frame(canvas, 4, 43, 55, 6);
    if(model->quota_remaining > 0) {
        uint8_t fill = (uint8_t)((51U * (uint32_t)model->quota_remaining) / 100U);
        if(fill == 0) fill = 1;
        canvas_draw_box(canvas, 6, 45, fill, 2);
    }

    codex_compact_draw(canvas, 95, 15, AlignCenter, "RESET");
    codex_monitor_format_reset_short(model, line, sizeof(line));
    codex_large_draw(canvas, 95, 23, AlignCenter, 1, line);
    codex_monitor_format_date_time(model, model->resets_at, line, sizeof(line));
    codex_compact_draw(canvas, 95, 36, AlignCenter, line);

    canvas_draw_line(canvas, 0, 50, 127, 50);
    snprintf(
        line,
        sizeof(line),
        "%u RESET%s",
        model->reset_credits,
        model->reset_credits == 1 ? "" : "S");
    codex_compact_draw(canvas, 2, 56, AlignLeft, line);
    char time_text[8];
    codex_monitor_format_clock(model, model->quota_fetched_at, time_text, sizeof(time_text));
    char updated[24];
    snprintf(updated, sizeof(updated), "UPDATED %s", time_text);
    codex_compact_draw(canvas, 126, 56, AlignRight, updated);
}

static const char* codex_task_activity_name(const CodexTaskModel* task) {
    if(task->activity == CodexActivityWorking) return "WORKING";
    if(task->activity == CodexActivityDone) return "DONE";
    return "IDLE";
}

static uint32_t codex_task_elapsed(const CodexTaskModel* task, uint32_t now) {
    if(task->started_at == 0) return 0;
    uint32_t end = task->activity == CodexActivityWorking ? now : task->updated_at;
    if(end < task->started_at) return 0;
    return end - task->started_at;
}

static void
    codex_monitor_format_task_duration(uint32_t seconds, char* text, size_t text_size) {
    if(seconds < 3600) {
        uint32_t minutes = (seconds + 59) / 60;
        snprintf(
            text,
            text_size,
            "%lu MINUTE%s",
            (unsigned long)minutes,
            minutes == 1 ? "" : "S");
    } else if(seconds < 86400) {
        uint32_t hours = seconds / 3600;
        snprintf(
            text, text_size, "%lu HOUR%s", (unsigned long)hours, hours == 1 ? "" : "S");
    } else {
        uint32_t days = seconds / 86400;
        snprintf(text, text_size, "%lu DAY%s", (unsigned long)days, days == 1 ? "" : "S");
    }
}

static void codex_monitor_format_freshness(
    const CodexTaskModel* task,
    uint32_t now,
    char* text,
    size_t text_size) {
    if(!task->token_available || task->updated_at == 0 || task->updated_at > now) {
        snprintf(text, text_size, "TOKEN DATA WAITING");
        return;
    }
    uint32_t age = now - task->updated_at;
    snprintf(
        text,
        text_size,
        "UPDATED %lu SECOND%s",
        (unsigned long)age,
        age == 1 ? "" : "S");
}

static void codex_monitor_draw_token_value(
    Canvas* canvas,
    int32_t x,
    int32_t y,
    Align align,
    uint64_t value) {
    char text[24];
    snprintf(text, sizeof(text), "%llu", (unsigned long long)value);
    if(strlen(text) <= 9)
        codex_large_draw(canvas, x, y, align, 1, text);
    else
        codex_compact_draw(canvas, x, y + 1, align, text);
}

static void codex_monitor_draw_tasks_overview(
    Canvas* canvas,
    const CodexMonitorModel* model,
    uint8_t selected_task) {
    char text[32];
    codex_monitor_draw_secondary_header(canvas, model, "TASKS");
    snprintf(text, sizeof(text), "%u WORKING", model->active_turns);
    codex_compact_draw(canvas, 2, 14, AlignLeft, text);
    snprintf(text, sizeof(text), "%u TASKS", model->task_count);
    codex_compact_draw(canvas, 126, 14, AlignRight, text);
    canvas_draw_line(canvas, 0, 20, 127, 20);

    if(model->task_count == 0) {
        codex_large_draw(canvas, 64, 27, AlignCenter, 1, "NO TASKS");
        codex_compact_draw(canvas, 64, 40, AlignCenter, "START A CODEX TASK");
        canvas_draw_line(canvas, 0, 53, 127, 53);
        codex_compact_draw(canvas, 64, 57, AlignCenter, "BACK TO HOME");
        return;
    }

    if(selected_task >= model->task_count) selected_task = model->task_count - 1;
    uint8_t first = selected_task >= 3 ? selected_task - 2 : 0;
    for(uint8_t row = 0; row < 3 && first + row < model->task_count; row++) {
        uint8_t index = first + row;
        const CodexTaskModel* task = &model->tasks[index];
        uint8_t row_top = 21 + row * 10;
        uint8_t y = row_top + 2;
        bool selected = index == selected_task;
        if(selected) {
            canvas_draw_box(canvas, 0, row_top, 128, 10);
            canvas_set_color(canvas, ColorWhite);
        }
        codex_compact_draw(canvas, 2, y, AlignLeft, task->label);
        codex_compact_draw(canvas, 44, y, AlignLeft, codex_task_activity_name(task));
        codex_monitor_format_clock(model, task->started_at, text, sizeof(text));
        codex_compact_draw(canvas, 126, y, AlignRight, text);
        if(selected) canvas_set_color(canvas, ColorBlack);
    }

    canvas_draw_line(canvas, 0, 53, 127, 53);
    const CodexTaskModel* selected = &model->tasks[selected_task];
    snprintf(text, sizeof(text), "TASK %u OF %u", selected->number, model->task_count);
    codex_compact_draw(canvas, 2, 57, AlignLeft, text);
    codex_compact_draw(
        canvas, 126, 57, AlignRight, selected->is_side ? "NO DETAILS" : "OK DETAILS");
}

static void codex_monitor_draw_task_live(
    Canvas* canvas,
    const CodexMonitorModel* model,
    const CodexTaskModel* task) {
    char text[32];
    codex_monitor_draw_secondary_header(canvas, model, task->label);
    codex_large_draw(canvas, 2, 14, AlignLeft, 1, codex_task_activity_name(task));
    codex_monitor_format_task_duration(
        codex_task_elapsed(task, codex_monitor_utc_now(model)), text, sizeof(text));
    codex_compact_draw(canvas, 126, 15, AlignRight, text);
    canvas_draw_line(canvas, 0, 23, 127, 23);

    if(!task->token_available) {
        codex_large_draw(canvas, 64, 30, AlignCenter, 1, "TOKENS WAITING");
        codex_compact_draw(canvas, 64, 43, AlignCenter, "TASK STATUS IS STILL LIVE");
    } else {
        codex_compact_draw(canvas, 31, 26, AlignCenter, "TOTAL TOKENS");
        codex_monitor_draw_token_value(canvas, 31, 34, AlignCenter, task->total_tokens);
        canvas_draw_line(canvas, 63, 24, 63, 44);
        codex_compact_draw(canvas, 95, 26, AlignCenter, "LAST CALL");
        codex_monitor_draw_token_value(canvas, 95, 34, AlignCenter, task->last_tokens);

        uint32_t context_percent = 0;
        if(task->context_window > 0) {
            context_percent = task->last_input_tokens >= task->context_window ?
                                  100 :
                                  (uint32_t)((task->last_input_tokens * 100U) /
                                             task->context_window);
        }
        snprintf(text, sizeof(text), "CONTEXT %lu%%", (unsigned long)context_percent);
        codex_compact_draw(canvas, 2, 47, AlignLeft, text);
        canvas_draw_frame(canvas, 49, 47, 78, 5);
        uint8_t fill = (uint8_t)((74U * context_percent) / 100U);
        if(fill > 0) canvas_draw_box(canvas, 51, 49, fill, 1);
    }

    canvas_draw_line(canvas, 0, 54, 127, 54);
    codex_monitor_format_freshness(task, codex_monitor_utc_now(model), text, sizeof(text));
    codex_compact_draw(canvas, 2, 58, AlignLeft, text);
}

static void codex_monitor_draw_task_tokens(
    Canvas* canvas,
    const CodexMonitorModel* model,
    const CodexTaskModel* task) {
    char text[32];
    codex_monitor_draw_secondary_header(canvas, model, task->label);
    if(!task->token_available) {
        codex_large_draw(canvas, 64, 27, AlignCenter, 1, "TOKENS WAITING");
        codex_compact_draw(canvas, 64, 42, AlignCenter, "NO TOKEN UPDATE YET");
    } else {
        const char* labels[] = {"INPUT", "CACHED INPUT", "OUTPUT", "REASONING OUTPUT"};
        uint64_t values[] = {
            task->input_tokens,
            task->cached_input_tokens,
            task->output_tokens,
            task->reasoning_output_tokens,
        };
        for(uint8_t index = 0; index < 4; index++) {
            uint8_t y = 14 + index * 10;
            codex_compact_draw(canvas, 2, y, AlignLeft, labels[index]);
            snprintf(text, sizeof(text), "%llu", (unsigned long long)values[index]);
            codex_compact_draw(canvas, 126, y, AlignRight, text);
            if(index < 3) canvas_draw_line(canvas, 2, y + 6, 125, y + 6);
        }
    }
    canvas_draw_line(canvas, 0, 53, 127, 53);
    snprintf(text, sizeof(text), "TOTAL %llu", (unsigned long long)task->total_tokens);
    codex_compact_draw(canvas, 2, 57, AlignLeft, text);
}

static void codex_monitor_draw_tasks(
    Canvas* canvas,
    const CodexMonitorModel* model,
    CodexTasksView tasks_view,
    uint8_t selected_task) {
    if(tasks_view == CodexTasksOverview || model->task_count == 0) {
        codex_monitor_draw_tasks_overview(canvas, model, selected_task);
        return;
    }
    if(selected_task >= model->task_count) selected_task = model->task_count - 1;
    const CodexTaskModel* task = &model->tasks[selected_task];
    if(tasks_view == CodexTaskLive)
        codex_monitor_draw_task_live(canvas, model, task);
    else
        codex_monitor_draw_task_tokens(canvas, model, task);
}

static void codex_monitor_draw_link(Canvas* canvas, const CodexMonitorModel* model) {
    codex_monitor_draw_secondary_header(canvas, model, "LINK");
    canvas_draw_line(canvas, 63, 12, 63, 36);
    codex_compact_draw(canvas, 31, 15, AlignCenter, "ACTIVE");
    codex_large_draw(canvas, 31, 23, AlignCenter, 1, codex_link_name(model));
    codex_compact_draw(canvas, 95, 15, AlignCenter, "CODEX");
    uint32_t now = furi_hal_rtc_get_timestamp();
    bool delayed = model->connected && model->last_payload_at > 0 &&
                   now > model->last_payload_at && now - model->last_payload_at > 120;
    codex_large_draw(
        canvas,
        95,
        23,
        AlignCenter,
        1,
        model->connected ? (delayed ? "DELAYED" : "ONLINE") : "OFFLINE");

    canvas_draw_line(canvas, 0, 37, 127, 37);
    bool usb_connected = furi_hal_power_get_usb_voltage() >= CODEX_USB_DISCONNECT_VOLTAGE;
    codex_compact_draw(canvas, 31, 39, AlignCenter, "USB");
    codex_compact_draw(canvas, 31, 46, AlignCenter, usb_connected ? "CONNECTED" : "DISCONNECTED");
    codex_compact_draw(canvas, 95, 39, AlignCenter, "BLUETOOTH");
    const char* bluetooth =
        model->link == CodexLinkBle ? "LINKED" : (model->ble_advertising ? "READY" : "OFF");
    codex_compact_draw(canvas, 95, 46, AlignCenter, bluetooth);
    canvas_draw_line(canvas, 63, 38, 63, 52);
    canvas_draw_line(canvas, 0, 53, 127, 53);
    char linked_for[40];
    codex_monitor_format_link_duration(model, linked_for, sizeof(linked_for));
    codex_compact_draw(canvas, 64, 57, AlignCenter, linked_for);
}

static void codex_monitor_usage_header_stats(
    Canvas* canvas,
    const char* left_label,
    uint32_t left_value,
    const char* right_label,
    uint32_t right_value) {
    char line[32];
    codex_compact_draw(canvas, 31, 14, AlignCenter, left_label);
    snprintf(line, sizeof(line), "%lu MILLION", (unsigned long)left_value);
    codex_compact_draw(canvas, 31, 21, AlignCenter, line);
    codex_compact_draw(canvas, 95, 14, AlignCenter, right_label);
    snprintf(line, sizeof(line), "%lu MILLION", (unsigned long)right_value);
    codex_compact_draw(canvas, 95, 21, AlignCenter, line);
    canvas_draw_line(canvas, 0, 27, 127, 27);
}

static void codex_monitor_draw_chart_value(
    Canvas* canvas,
    int32_t x,
    int32_t y,
    Align align,
    const char* text) {
    uint8_t width = codex_compact_width(text);
    int32_t left = x;
    if(align == AlignCenter)
        left -= width / 2;
    else if(align == AlignRight)
        left -= width;
    if(left < 1) left = 1;
    if(left + width > 126) left = 126 - width;
    if(y < 13) y = 13;
    if(y > 44) y = 44;

    canvas_set_color(canvas, ColorWhite);
    canvas_draw_box(canvas, left - 1, y - 1, width + 2, 7);
    canvas_set_color(canvas, ColorBlack);
    codex_compact_draw(canvas, left, y, AlignLeft, text);
}

static void codex_monitor_draw_usage_daily(
    Canvas* canvas,
    const CodexMonitorModel* model,
    uint8_t range_days) {
    if(range_days > CODEX_USAGE_DAYS) range_days = CODEX_USAGE_DAYS;
    if(range_days < 2) range_days = 2;
    uint8_t first = CODEX_USAGE_DAYS - range_days;
    uint32_t peak = 0;
    uint8_t peak_index = first;
    for(uint8_t index = first; index < CODEX_USAGE_DAYS; index++) {
        if(model->daily_millions[index] > peak) {
            peak = model->daily_millions[index];
            peak_index = index;
        }
    }
    const uint8_t chart_left = 4;
    const uint8_t chart_top = 14;
    const uint8_t chart_right = 123;
    const uint8_t chart_bottom = 50;
    canvas_draw_line(canvas, chart_left, chart_bottom, chart_right, chart_bottom);

    int32_t previous_x = chart_left;
    int32_t previous_y = chart_bottom;
    int32_t peak_x = chart_left;
    int32_t peak_y = chart_bottom;
    int32_t latest_x = chart_right;
    int32_t latest_y = chart_bottom;
    for(uint8_t offset = 0; offset < range_days; offset++) {
        uint8_t index = first + offset;
        int32_t x =
            chart_left + ((uint32_t)offset * (chart_right - chart_left)) / (range_days - 1);
        int32_t y = chart_bottom;
        if(peak > 0)
            y -= ((uint64_t)model->daily_millions[index] * (chart_bottom - chart_top)) / peak;
        if(offset > 0) canvas_draw_line(canvas, previous_x, previous_y, x, y);
        canvas_draw_dot(canvas, x, y);
        previous_x = x;
        previous_y = y;
        if(index == peak_index) {
            peak_x = x;
            peak_y = y;
            canvas_draw_frame(canvas, x - 1, y - 1, 3, 3);
        }
        if(index == CODEX_USAGE_DAYS - 1) {
            latest_x = x;
            latest_y = y;
            canvas_draw_box(canvas, x - 1, y - 1, 3, 3);
        }
    }

    char line[20];
    snprintf(line, sizeof(line), "%luM", (unsigned long)peak);
    int32_t peak_label_y = peak_y + 4;
    if(peak_index != CODEX_USAGE_DAYS - 1 && peak_x > 90 && latest_y < 26)
        peak_label_y = peak_y + 11;
    codex_monitor_draw_chart_value(canvas, peak_x, peak_label_y, AlignCenter, line);
    if(peak_index != CODEX_USAGE_DAYS - 1) {
        snprintf(
            line, sizeof(line), "%luM", (unsigned long)model->daily_millions[CODEX_USAGE_DAYS - 1]);
        int32_t latest_label_y = latest_y < 22 ? latest_y + 4 : latest_y - 7;
        codex_monitor_draw_chart_value(canvas, latest_x + 3, latest_label_y, AlignRight, line);
    }

    uint32_t date_span = (uint32_t)(range_days - 1) * 86400U;
    uint32_t start_date =
        model->usage_latest_date >= date_span ? model->usage_latest_date - date_span : 0;
    codex_monitor_format_month_day(model, start_date, line, sizeof(line));
    codex_compact_draw(canvas, 2, 56, AlignLeft, line);
    snprintf(line, sizeof(line), "%u DAYS", range_days);
    codex_compact_draw(canvas, 64, 56, AlignCenter, line);
    codex_monitor_format_month_day(model, model->usage_latest_date, line, sizeof(line));
    codex_compact_draw(canvas, 126, 56, AlignRight, line);
}

static void codex_monitor_draw_usage_weekly(Canvas* canvas, const CodexMonitorModel* model) {
    uint32_t weeks[4] = {0};
    for(uint8_t week = 0; week < 4; week++) {
        uint8_t first = CODEX_USAGE_DAYS - 28 + week * 7;
        for(uint8_t day = 0; day < 7; day++)
            weeks[week] += model->daily_millions[first + day];
    }
    uint32_t peak = weeks[0];
    for(uint8_t week = 1; week < 4; week++) {
        if(weeks[week] > peak) peak = weeks[week];
    }
    codex_monitor_usage_header_stats(canvas, "PEAK WEEK", peak, "THIS WEEK", weeks[3]);

    for(uint8_t week = 0; week < 4; week++) {
        uint8_t x = 19 + week * 29;
        uint8_t height = peak == 0 ? 1 : (uint8_t)(((uint64_t)weeks[week] * 20U) / peak);
        if(height == 0) height = 1;
        canvas_draw_frame(canvas, x, 50 - height, 13, height + 1);
        if(week == 3 && height > 3) canvas_draw_box(canvas, x + 2, 52 - height, 9, height - 3);
    }
    canvas_draw_line(canvas, 4, 50, 123, 50);
    codex_compact_draw(canvas, 64, 56, AlignCenter, "4 WEEKS");
}

static void codex_monitor_draw_usage_total(Canvas* canvas, const CodexMonitorModel* model) {
    char value[32];
    const char* labels[5] = {
        "TOTAL TOKENS", "PEAK DAY", "LONGEST TASK", "CURRENT STREAK", "LONGEST STREAK"};
    for(uint8_t row = 0; row < 5; row++) {
        uint8_t y = 14 + row * 9;
        if(row == 0) {
            snprintf(value, sizeof(value), "%llu", (unsigned long long)model->lifetime_tokens);
        } else if(row == 1) {
            snprintf(value, sizeof(value), "%llu", (unsigned long long)model->peak_daily_tokens);
        } else if(row == 2) {
            codex_monitor_format_duration(model->longest_running_turn_sec, value, sizeof(value));
        } else if(row == 3) {
            snprintf(value, sizeof(value), "%u DAYS", model->current_streak_days);
        } else {
            snprintf(value, sizeof(value), "%u DAYS", model->longest_streak_days);
        }
        codex_compact_draw(canvas, 2, y, AlignLeft, labels[row]);
        codex_compact_draw(canvas, 126, y, AlignRight, value);
        if(row < 4) canvas_draw_line(canvas, 2, y + 6, 125, y + 6);
    }
}

static void codex_monitor_draw_usage(
    Canvas* canvas,
    const CodexMonitorModel* model,
    CodexUsageView usage_view,
    uint8_t range_days) {
    codex_monitor_draw_secondary_header(canvas, model, "USAGE");
    if(!model->usage_available) {
        codex_large_draw(canvas, 64, 22, AlignCenter, 1, "NO DATA");
        codex_compact_draw(canvas, 64, 38, AlignCenter, "WAITING FOR CODEX USAGE");
        return;
    }
    if(usage_view == CodexUsageDaily) {
        codex_monitor_draw_usage_daily(canvas, model, range_days);
    } else if(usage_view == CodexUsageWeekly) {
        codex_monitor_draw_usage_weekly(canvas, model);
    } else {
        codex_monitor_draw_usage_total(canvas, model);
    }
}

static void codex_monitor_draw(Canvas* canvas, void* context) {
    CodexMonitorApp* app = context;
    furi_mutex_acquire(app->mutex, FuriWaitForever);
    canvas_clear(canvas);
    canvas_set_color(canvas, ColorBlack);
    if(app->page == CodexPageHome) {
        codex_monitor_draw_home(canvas, &app->model);
    } else if(app->page == CodexPageLink) {
        codex_monitor_draw_link(canvas, &app->model);
    } else if(!app->model.connected) {
        const char* title = app->page == CodexPageQuota ? "QUOTA" :
                             (app->page == CodexPageUsage ? "USAGE" : "TASKS");
        codex_monitor_draw_offline_page(canvas, &app->model, title);
    } else if(app->page == CodexPageQuota) {
        codex_monitor_draw_quota(canvas, &app->model);
    } else if(app->page == CodexPageUsage) {
        codex_monitor_draw_usage(
            canvas, &app->model, app->usage_view, app->usage_range_days);
    } else {
        codex_monitor_draw_tasks(
            canvas, &app->model, app->tasks_view, app->selected_task);
    }
    furi_mutex_release(app->mutex);
}

static void codex_monitor_input(InputEvent* event, void* context) {
    CodexMonitorApp* app = context;
    CodexEvent app_event = {
        .type = CodexEventInput,
        .data.input = *event,
    };
    furi_message_queue_put(app->event_queue, &app_event, 0);
}

static void codex_monitor_bt_status(BtStatus status, void* context) {
    CodexMonitorApp* app = context;
    CodexEvent event = {
        .type = CodexEventBtStatus,
        .data.bt_status = status,
    };
    furi_message_queue_put(app->event_queue, &event, 0);
}

static uint16_t codex_monitor_ble_event(SerialServiceEvent event, void* context) {
    CodexMonitorApp* app = context;
    if(event.event == SerialServiceEventTypeDataReceived && event.data.size > 0) {
        CodexEvent app_event = {.type = CodexEventBleData};
        uint16_t size = event.data.size;
        if(size > CODEX_BLE_PACKET_MAX) size = CODEX_BLE_PACKET_MAX;
        app_event.data.ble_packet.size = size;
        memcpy(app_event.data.ble_packet.data, event.data.buffer, size);
        app_event.data.ble_packet.data[size] = '\0';
        furi_message_queue_put(app->event_queue, &app_event, 0);
    }
    return CODEX_BLE_PACKET_MAX;
}

static bool codex_parse_long(const char* value, long* result) {
    if(!value || !*value) return false;
    char* end = NULL;
    long parsed = strtol(value, &end, 10);
    if(!end || *end != '\0') return false;
    *result = parsed;
    return true;
}

static bool codex_parse_uint64(const char* value, uint64_t* result) {
    if(!value || !*value || *value == '-') return false;
    char* end = NULL;
    unsigned long long parsed = strtoull(value, &end, 10);
    if(!end || *end != '\0') return false;
    *result = (uint64_t)parsed;
    return true;
}

static bool codex_parse_base36(const char* value, uint64_t* result) {
    if(!value || !*value) return false;
    uint64_t parsed = 0;
    while(*value) {
        uint8_t digit;
        if(*value >= '0' && *value <= '9')
            digit = (uint8_t)(*value - '0');
        else if(*value >= 'A' && *value <= 'Z')
            digit = (uint8_t)(*value - 'A' + 10);
        else
            return false;
        if(parsed > (UINT64_MAX - digit) / 36U) return false;
        parsed = parsed * 36U + digit;
        value++;
    }
    *result = parsed;
    return true;
}

static int8_t codex_usage_alphabet_index(char value) {
    if(value >= '0' && value <= '9') return value - '0';
    if(value >= 'A' && value <= 'Z') return value - 'A' + 10;
    if(value >= 'a' && value <= 'z') return value - 'a' + 36;
    if(value == '-') return 62;
    if(value == '_') return 63;
    return -1;
}

static bool codex_monitor_apply_args(CodexMonitorModel* model, const char* args, CodexLink link) {
    char buffer[192];
    snprintf(buffer, sizeof(buffer), "%s", args ? args : "");

    CodexMonitorModel next = *model;
    bool version_ok = false;
    char* cursor = buffer;
    while(*cursor) {
        while(*cursor == ' ')
            cursor++;
        if(!*cursor) break;
        char* token = cursor;
        while(*cursor && *cursor != ' ')
            cursor++;
        if(*cursor) {
            *cursor = '\0';
            cursor++;
        }
        char* separator = strchr(token, '=');
        if(!separator) continue;
        *separator = '\0';
        const char* key = token;
        const char* value = separator + 1;
        long number = 0;

        if(strcmp(key, "v") == 0) {
            version_ok = codex_parse_long(value, &number) && (number == 1 || number == 2);
        } else if(strcmp(key, "q") == 0 && codex_parse_long(value, &number)) {
            if(number < -1 || number > 100) return false;
            next.quota_remaining = (int32_t)number;
        } else if(strcmp(key, "d") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.duration_minutes = (uint32_t)number;
        } else if(strcmp(key, "r") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.resets_at = (uint32_t)number;
        } else if(strcmp(key, "h") == 0 && codex_parse_long(value, &number)) {
            if(number < -1 || number > 23) return false;
            next.reset_hour = (int8_t)number;
        } else if(strcmp(key, "m") == 0 && codex_parse_long(value, &number)) {
            if(number < -1 || number > 59) return false;
            next.reset_minute = (int8_t)number;
        } else if(strcmp(key, "c") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.reset_credits = (uint8_t)(number > 99 ? 99 : number);
        } else if(strcmp(key, "n") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.active_turns = (uint8_t)(number > 99 ? 99 : number);
        } else if(strcmp(key, "a") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.activity_since = (uint32_t)number;
        } else if(strcmp(key, "l") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.last_completed_at = (uint32_t)number;
        } else if(strcmp(key, "f") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.completion_sequence = (uint32_t)number;
        } else if(strcmp(key, "t") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.quota_fetched_at = (uint32_t)number;
        } else if(strcmp(key, "z") == 0 && codex_parse_long(value, &number)) {
            if(number < -86400 || number > 86400) return false;
            next.utc_offset_seconds = (int32_t)number;
        } else if(strcmp(key, "e") == 0 && codex_parse_long(value, &number)) {
            if(number < 0 || number > 3) return false;
            next.health_flags = (uint8_t)number;
        } else if(strcmp(key, "p") == 0 && value[0] && !value[1]) {
            next.plan = value[0];
        } else if(strcmp(key, "s") == 0 && value[0] && !value[1]) {
            if(value[0] == 'W')
                next.activity = CodexActivityWorking;
            else if(value[0] == 'D')
                next.activity = CodexActivityDone;
            else if(value[0] == 'I')
                next.activity = CodexActivityIdle;
            else
                return false;
        }
    }

    if(!version_ok) return false;
    uint32_t received_at = furi_hal_rtc_get_timestamp();
    if(!next.connected || next.link != link || next.link_since == 0) {
        next.link_since = received_at;
    }
    next.connected = true;
    next.link = link;
    next.last_payload_at = received_at;
    *model = next;
    return true;
}

static bool
    codex_monitor_apply_usage_args(CodexMonitorModel* model, const char* args, CodexLink link) {
    char buffer[192];
    snprintf(buffer, sizeof(buffer), "%s", args ? args : "");

    CodexMonitorModel next = *model;
    bool version_ok = false;
    bool daily_ok = false;
    char* cursor = buffer;
    while(*cursor) {
        while(*cursor == ' ')
            cursor++;
        if(!*cursor) break;
        char* token = cursor;
        while(*cursor && *cursor != ' ')
            cursor++;
        if(*cursor) {
            *cursor = '\0';
            cursor++;
        }
        char* separator = strchr(token, '=');
        if(!separator) continue;
        *separator = '\0';
        const char* key = token;
        const char* value = separator + 1;
        long number = 0;
        uint64_t wide_number = 0;

        if(strcmp(key, "v") == 0) {
            version_ok = codex_parse_long(value, &number) && number == 1;
        } else if(strcmp(key, "u") == 0 && codex_parse_uint64(value, &wide_number)) {
            next.lifetime_tokens = wide_number;
        } else if(strcmp(key, "x") == 0 && codex_parse_uint64(value, &wide_number)) {
            next.peak_daily_tokens = wide_number;
        } else if(strcmp(key, "l") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.longest_running_turn_sec = (uint32_t)number;
        } else if(strcmp(key, "c") == 0 && codex_parse_long(value, &number)) {
            if(number < 0 || number > UINT16_MAX) return false;
            next.current_streak_days = (uint16_t)number;
        } else if(strcmp(key, "g") == 0 && codex_parse_long(value, &number)) {
            if(number < 0 || number > UINT16_MAX) return false;
            next.longest_streak_days = (uint16_t)number;
        } else if(strcmp(key, "f") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.usage_fetched_at = (uint32_t)number;
        } else if(strcmp(key, "e") == 0 && codex_parse_long(value, &number)) {
            if(number < 0) return false;
            next.usage_latest_date = (uint32_t)number;
        } else if(strcmp(key, "z") == 0) {
            if(strlen(value) != CODEX_USAGE_DAYS * 3U) return false;
            for(uint8_t index = 0; index < CODEX_USAGE_DAYS; index++) {
                int8_t high = codex_usage_alphabet_index(value[index * 3]);
                int8_t middle = codex_usage_alphabet_index(value[index * 3 + 1]);
                int8_t low = codex_usage_alphabet_index(value[index * 3 + 2]);
                if(high < 0 || middle < 0 || low < 0) return false;
                next.daily_millions[index] = ((uint32_t)high << 12) | ((uint32_t)middle << 6) |
                                             (uint32_t)low;
            }
            daily_ok = true;
        }
    }

    if(!version_ok || !daily_ok) return false;
    uint32_t received_at = furi_hal_rtc_get_timestamp();
    if(!next.connected || next.link != link || next.link_since == 0) {
        next.link_since = received_at;
    }
    next.usage_available = true;
    next.connected = true;
    next.link = link;
    next.last_payload_at = received_at;
    *model = next;
    return true;
}

static void codex_monitor_mark_received(CodexMonitorModel* model, CodexLink link) {
    uint32_t received_at = furi_hal_rtc_get_timestamp();
    if(!model->connected || model->link != link || model->link_since == 0) {
        model->link_since = received_at;
    }
    model->connected = true;
    model->link = link;
    model->last_payload_at = received_at;
}

static bool codex_monitor_apply_task_roster_args(
    CodexMonitorModel* model,
    const char* args,
    CodexLink link) {
    char buffer[192];
    snprintf(buffer, sizeof(buffer), "%s", args ? args : "");
    bool version_ok = false;
    bool count_ok = false;
    uint8_t count = 0;
    char* cursor = buffer;
    while(*cursor) {
        while(*cursor == ' ')
            cursor++;
        if(!*cursor) break;
        char* token = cursor;
        while(*cursor && *cursor != ' ')
            cursor++;
        if(*cursor) *cursor++ = '\0';
        char* separator = strchr(token, '=');
        if(!separator) continue;
        *separator = '\0';
        const char* key = token;
        const char* value = separator + 1;
        long number = 0;
        if(strcmp(key, "v") == 0) {
            version_ok = codex_parse_long(value, &number) && number == 1;
        } else if(strcmp(key, "n") == 0 && codex_parse_long(value, &number)) {
            if(number < 0 || number > CODEX_TASK_SLOTS) return false;
            count = (uint8_t)number;
            count_ok = true;
        }
    }
    if(!version_ok || !count_ok) return false;
    model->task_count = count;
    for(uint8_t index = count; index < CODEX_TASK_SLOTS; index++) {
        memset(&model->tasks[index], 0, sizeof(CodexTaskModel));
    }
    codex_monitor_mark_received(model, link);
    return true;
}

static bool codex_monitor_apply_task_args(
    CodexMonitorModel* model,
    const char* args,
    CodexLink link,
    uint8_t* applied_slot) {
    char buffer[192];
    snprintf(buffer, sizeof(buffer), "%s", args ? args : "");
    bool version_ok = false;
    bool slot_ok = false;
    uint8_t slot = 0;
    CodexTaskModel parsed;
    memset(&parsed, 0, sizeof(parsed));
    snprintf(parsed.label, sizeof(parsed.label), "CODEX");
    char* cursor = buffer;
    while(*cursor) {
        while(*cursor == ' ')
            cursor++;
        if(!*cursor) break;
        char* token = cursor;
        while(*cursor && *cursor != ' ')
            cursor++;
        if(*cursor) *cursor++ = '\0';
        char* separator = strchr(token, '=');
        if(!separator) continue;
        *separator = '\0';
        const char* key = token;
        const char* value = separator + 1;
        long number = 0;
        uint64_t wide = 0;
        if(strcmp(key, "v") == 0) {
            version_ok = codex_parse_long(value, &number) && number == 1;
        } else if(strcmp(key, "s") == 0 && value[0] && !value[1]) {
            if(value[0] == 'W')
                parsed.activity = CodexActivityWorking;
            else if(value[0] == 'D')
                parsed.activity = CodexActivityDone;
            else if(value[0] == 'I')
                parsed.activity = CodexActivityIdle;
            else
                return false;
        } else if(strcmp(key, "k") == 0 && codex_parse_base36(value, &wide)) {
            if(wide >= CODEX_TASK_SLOTS) return false;
            slot = (uint8_t)wide;
            slot_ok = true;
        } else if(strcmp(key, "d") == 0 && codex_parse_base36(value, &wide)) {
            if(wide == 0 || wide > 99) return false;
            parsed.number = (uint8_t)wide;
        } else if(strcmp(key, "b") == 0) {
            size_t label_length = strlen(value);
            if(label_length == 0 || label_length > CODEX_TASK_LABEL_MAX) return false;
            for(size_t index = 0; index < label_length; index++) {
                char character = value[index];
                if(character == '_') character = ' ';
                if(!((character >= 'A' && character <= 'Z') ||
                     (character >= '0' && character <= '9') || character == ' ' ||
                     character == '-'))
                    return false;
                parsed.label[index] = character;
            }
            parsed.label[label_length] = '\0';
        } else if(strcmp(key, "e") == 0 && codex_parse_base36(value, &wide)) {
            if(wide > 1) return false;
            parsed.token_available = wide == 1;
        } else if(strcmp(key, "x") == 0 && codex_parse_base36(value, &wide)) {
            if(wide > 1) return false;
            parsed.is_side = wide == 1;
        } else if(strcmp(key, "a") == 0 && codex_parse_base36(value, &wide)) {
            if(wide > UINT32_MAX) return false;
            parsed.started_at = (uint32_t)wide;
        } else if(strcmp(key, "u") == 0 && codex_parse_base36(value, &wide)) {
            if(wide > UINT32_MAX) return false;
            parsed.updated_at = (uint32_t)wide;
        } else if(strcmp(key, "t") == 0 && codex_parse_base36(value, &wide)) {
            parsed.total_tokens = wide;
        } else if(strcmp(key, "l") == 0 && codex_parse_base36(value, &wide)) {
            parsed.last_tokens = wide;
        } else if(strcmp(key, "g") == 0 && codex_parse_base36(value, &wide)) {
            parsed.last_input_tokens = wide;
        } else if(strcmp(key, "i") == 0 && codex_parse_base36(value, &wide)) {
            parsed.input_tokens = wide;
        } else if(strcmp(key, "c") == 0 && codex_parse_base36(value, &wide)) {
            parsed.cached_input_tokens = wide;
        } else if(strcmp(key, "o") == 0 && codex_parse_base36(value, &wide)) {
            parsed.output_tokens = wide;
        } else if(strcmp(key, "r") == 0 && codex_parse_base36(value, &wide)) {
            parsed.reasoning_output_tokens = wide;
        } else if(strcmp(key, "w") == 0 && codex_parse_base36(value, &wide)) {
            if(wide > UINT32_MAX) return false;
            parsed.context_window = (uint32_t)wide;
        }
    }
    if(!version_ok || !slot_ok || parsed.number == 0 || slot >= model->task_count) return false;
    parsed.valid = true;
    model->tasks[slot] = parsed;
    if(applied_slot) *applied_slot = slot;
    codex_monitor_mark_received(model, link);
    return true;
}

static void codex_monitor_reconcile_selected_task(
    CodexMonitorApp* app,
    bool roster_complete) {
    if(app->model.task_count == 0) {
        app->selected_task = 0;
        app->selected_task_number = 0;
        app->tasks_view = CodexTasksOverview;
        return;
    }

    if(app->selected_task_number != 0) {
        for(uint8_t index = 0; index < app->model.task_count; index++) {
            const CodexTaskModel* task = &app->model.tasks[index];
            if(task->valid && task->number == app->selected_task_number) {
                app->selected_task = index;
                return;
            }
        }
    }
    if(!roster_complete) return;

    if(app->selected_task >= app->model.task_count) app->selected_task = 0;
    if(app->tasks_view != CodexTasksOverview && app->model.tasks[app->selected_task].is_side) {
        bool found = false;
        for(uint8_t index = 0; index < app->model.task_count; index++) {
            if(app->model.tasks[index].valid && !app->model.tasks[index].is_side) {
                app->selected_task = index;
                found = true;
                break;
            }
        }
        if(!found) app->tasks_view = CodexTasksOverview;
    }
    app->selected_task_number = app->model.tasks[app->selected_task].number;
}

static void codex_monitor_notify_transition(
    CodexMonitorApp* app,
    CodexActivity previous,
    CodexActivity current) {
    if(previous == current) return;
    if(current == CodexActivityWorking || current == CodexActivityDone) {
        furi_mutex_acquire(app->mutex, FuriWaitForever);
        app->model.animation_frame = 0;
        app->last_animation_tick =
            current == CodexActivityDone ? furi_get_tick() : 0;
        if(current == CodexActivityWorking) {
            app->led_phase = 0;
            app->last_led_tick = 0;
        }
        furi_mutex_release(app->mutex);
        if(current == CodexActivityWorking) {
            notification_message(app->notifications, &sequence_display_backlight_on);
        } else {
            codex_monitor_led_off(app);
        }
    } else {
        codex_monitor_led_off(app);
    }
}

static void codex_monitor_notify_task_completions(
    CodexMonitorApp* app,
    uint32_t previous,
    uint32_t current) {
    if(!app->completion_sequence_known) {
        app->completion_sequence_known = true;
        return;
    }
    if(current <= previous) return;

    uint32_t count = current - previous;
    if(count > CODEX_TASK_SLOTS) count = CODEX_TASK_SLOTS;
    for(uint32_t index = 0; index < count; index++) {
        notification_message(app->notifications, &sequence_success);
    }
}

static void codex_monitor_cli(PipeSide* pipe, FuriString* args, void* context) {
    (void)pipe;
    CodexMonitorApp* app = context;
    CodexActivity previous;
    CodexActivity current;
    uint32_t previous_completion_sequence;
    uint32_t current_completion_sequence;
    bool accepted;

    furi_mutex_acquire(app->mutex, FuriWaitForever);
    previous = app->model.activity;
    previous_completion_sequence = app->model.completion_sequence;
    accepted = codex_monitor_apply_args(&app->model, furi_string_get_cstr(args), CodexLinkUsb);
    current = app->model.activity;
    current_completion_sequence = app->model.completion_sequence;
    furi_mutex_release(app->mutex);

    if(!accepted) {
        printf("ERR invalid codexmon payload\r\n");
        return;
    }

    codex_monitor_notify_transition(app, previous, current);
    codex_monitor_notify_task_completions(
        app, previous_completion_sequence, current_completion_sequence);
    view_port_update(app->view_port);
    printf("OK\r\n");
}

static void codex_monitor_usage_cli(PipeSide* pipe, FuriString* args, void* context) {
    (void)pipe;
    CodexMonitorApp* app = context;
    bool accepted;

    furi_mutex_acquire(app->mutex, FuriWaitForever);
    accepted =
        codex_monitor_apply_usage_args(&app->model, furi_string_get_cstr(args), CodexLinkUsb);
    furi_mutex_release(app->mutex);

    if(!accepted) {
        printf("ERR invalid codexuse payload\r\n");
        return;
    }
    view_port_update(app->view_port);
    printf("OK\r\n");
}

static void codex_monitor_tasks_cli(PipeSide* pipe, FuriString* args, void* context) {
    (void)pipe;
    CodexMonitorApp* app = context;
    bool accepted;
    furi_mutex_acquire(app->mutex, FuriWaitForever);
    accepted =
        codex_monitor_apply_task_roster_args(&app->model, furi_string_get_cstr(args), CodexLinkUsb);
    codex_monitor_reconcile_selected_task(app, false);
    furi_mutex_release(app->mutex);
    if(!accepted) {
        printf("ERR invalid codextasks payload\r\n");
        return;
    }
    view_port_update(app->view_port);
    printf("OK\r\n");
}

static void codex_monitor_task_cli(PipeSide* pipe, FuriString* args, void* context) {
    (void)pipe;
    CodexMonitorApp* app = context;
    bool accepted;
    uint8_t applied_slot = 0;
    furi_mutex_acquire(app->mutex, FuriWaitForever);
    accepted = codex_monitor_apply_task_args(
        &app->model, furi_string_get_cstr(args), CodexLinkUsb, &applied_slot);
    if(accepted) {
        codex_monitor_reconcile_selected_task(
            app, applied_slot + 1U >= app->model.task_count);
    }
    furi_mutex_release(app->mutex);
    if(!accepted) {
        printf("ERR invalid codextask payload\r\n");
        return;
    }
    view_port_update(app->view_port);
    printf("OK\r\n");
}

static void codex_monitor_process_ble(CodexMonitorApp* app, CodexBlePacket* packet) {
    while(packet->size > 0 &&
          (packet->data[packet->size - 1] == '\r' || packet->data[packet->size - 1] == '\n')) {
        packet->data[--packet->size] = '\0';
    }

    const char monitor_prefix[] = "codexmon ";
    const char usage_prefix[] = "codexuse ";
    const char tasks_prefix[] = "codextasks ";
    const char task_prefix[] = "codextask ";
    bool is_monitor = packet->size > sizeof(monitor_prefix) - 1 &&
                      strncmp(packet->data, monitor_prefix, sizeof(monitor_prefix) - 1) == 0;
    bool is_usage = packet->size > sizeof(usage_prefix) - 1 &&
                    strncmp(packet->data, usage_prefix, sizeof(usage_prefix) - 1) == 0;
    bool is_tasks = packet->size > sizeof(tasks_prefix) - 1 &&
                    strncmp(packet->data, tasks_prefix, sizeof(tasks_prefix) - 1) == 0;
    bool is_task = packet->size > sizeof(task_prefix) - 1 &&
                   strncmp(packet->data, task_prefix, sizeof(task_prefix) - 1) == 0;
    bool accepted = is_monitor || is_usage || is_tasks || is_task;
    uint8_t applied_slot = 0;
    CodexActivity previous = CodexActivityIdle;
    CodexActivity current = CodexActivityIdle;
    uint32_t previous_completion_sequence = 0;
    uint32_t current_completion_sequence = 0;
    if(accepted) {
        furi_mutex_acquire(app->mutex, FuriWaitForever);
        previous = app->model.activity;
        previous_completion_sequence = app->model.completion_sequence;
        if(is_monitor) {
            accepted = codex_monitor_apply_args(
                &app->model, packet->data + sizeof(monitor_prefix) - 1, CodexLinkBle);
        } else if(is_usage) {
            accepted = codex_monitor_apply_usage_args(
                &app->model, packet->data + sizeof(usage_prefix) - 1, CodexLinkBle);
        } else if(is_tasks) {
            accepted = codex_monitor_apply_task_roster_args(
                &app->model, packet->data + sizeof(tasks_prefix) - 1, CodexLinkBle);
            if(accepted) codex_monitor_reconcile_selected_task(app, false);
        } else {
            accepted = codex_monitor_apply_task_args(
                &app->model,
                packet->data + sizeof(task_prefix) - 1,
                CodexLinkBle,
                &applied_slot);
            if(accepted) {
                codex_monitor_reconcile_selected_task(
                    app, applied_slot + 1U >= app->model.task_count);
            }
        }
        current = app->model.activity;
        current_completion_sequence = app->model.completion_sequence;
        furi_mutex_release(app->mutex);
    }

    if(accepted) {
        codex_monitor_notify_transition(app, previous, current);
        if(is_monitor) {
            codex_monitor_notify_task_completions(
                app, previous_completion_sequence, current_completion_sequence);
        }
    }
    if(app->ble_profile) {
        uint8_t ok[] = "OK\r\n";
        uint8_t error[] = "ERR invalid Codex payload\r\n";
        if(accepted) {
            codex_ble_profile_tx(app->ble_profile, ok, sizeof(ok) - 1);
        } else {
            codex_ble_profile_tx(app->ble_profile, error, sizeof(error) - 1);
        }
        codex_ble_profile_set_callback(
            app->ble_profile, CODEX_BLE_PACKET_MAX, codex_monitor_ble_event, app);
    }
    view_port_update(app->view_port);
}

static bool codex_monitor_process_input_event(CodexMonitorApp* app, const InputEvent* input) {
    if(input->type == InputTypeLong) {
        if(input->key == InputKeyBack) {
            furi_mutex_acquire(app->mutex, FuriWaitForever);
            bool should_exit =
                app->page == CodexPageHome && app->back_press_started_on_home;
            app->back_press_started_on_home = false;
            furi_mutex_release(app->mutex);
            if(should_exit) return false;
        } else if(input->key == InputKeyOk) {
            furi_mutex_acquire(app->mutex, FuriWaitForever);
            bool is_home = app->page == CodexPageHome;
            furi_mutex_release(app->mutex);
            if(is_home) {
                bool sent = codex_monitor_open_chatgpt(app);
                notification_message(
                    app->notifications, sent ? &sequence_single_vibro : &sequence_error);
            }
        }
        return true;
    }
    if(input->type == InputTypeRelease && input->key == InputKeyBack) {
        furi_mutex_acquire(app->mutex, FuriWaitForever);
        app->back_press_started_on_home = false;
        furi_mutex_release(app->mutex);
        return true;
    }
    if(input->type != InputTypePress) return true;

    furi_mutex_acquire(app->mutex, FuriWaitForever);
    if(input->key == InputKeyBack) {
        if(app->page == CodexPageHome) {
            app->back_press_started_on_home = true;
            furi_mutex_release(app->mutex);
            return true;
        }
        app->back_press_started_on_home = false;
        if(app->page == CodexPageTasks && app->tasks_view != CodexTasksOverview)
            app->tasks_view = CodexTasksOverview;
        else
            app->page = CodexPageHome;
    } else if(app->page == CodexPageHome) {
        if(input->key == InputKeyLeft)
            app->page = CodexPageQuota;
        else if(input->key == InputKeyDown)
            app->page = CodexPageUsage;
        else if(input->key == InputKeyRight) {
            app->page = CodexPageTasks;
            app->tasks_view = CodexTasksOverview;
            if(app->model.task_count > 0) {
                app->selected_task_number =
                    app->model.tasks[app->selected_task].number;
            }
        } else if(input->key == InputKeyUp)
            app->page = CodexPageLink;
    } else if(app->page == CodexPageTasks) {
        if(app->tasks_view == CodexTasksOverview) {
            if(input->key == InputKeyLeft) {
                app->page = CodexPageUsage;
            } else if(input->key == InputKeyRight) {
                app->page = CodexPageLink;
            } else if(input->key == InputKeyUp && app->model.task_count > 0) {
                app->selected_task = app->selected_task == 0 ?
                                         app->model.task_count - 1 :
                                         app->selected_task - 1;
            } else if(input->key == InputKeyDown && app->model.task_count > 0) {
                app->selected_task = (app->selected_task + 1) % app->model.task_count;
            } else if(
                input->key == InputKeyOk && app->model.task_count > 0 &&
                !app->model.tasks[app->selected_task].is_side) {
                app->selected_task_number =
                    app->model.tasks[app->selected_task].number;
                app->tasks_view = CodexTaskLive;
            }
            if((input->key == InputKeyUp || input->key == InputKeyDown) &&
               app->model.task_count > 0) {
                app->selected_task_number =
                    app->model.tasks[app->selected_task].number;
            }
        } else {
            if(input->key == InputKeyUp && app->model.task_count > 0) {
                uint8_t candidate = app->selected_task;
                for(uint8_t offset = 0; offset < app->model.task_count; offset++) {
                    candidate = candidate == 0 ? app->model.task_count - 1 : candidate - 1;
                    if(!app->model.tasks[candidate].is_side) {
                        app->selected_task = candidate;
                        app->selected_task_number =
                            app->model.tasks[candidate].number;
                        break;
                    }
                }
            } else if(input->key == InputKeyDown && app->model.task_count > 0) {
                uint8_t candidate = app->selected_task;
                for(uint8_t offset = 0; offset < app->model.task_count; offset++) {
                    candidate = (candidate + 1) % app->model.task_count;
                    if(!app->model.tasks[candidate].is_side) {
                        app->selected_task = candidate;
                        app->selected_task_number =
                            app->model.tasks[candidate].number;
                        break;
                    }
                }
            } else if(input->key == InputKeyOk) {
                app->tasks_view = app->tasks_view == CodexTaskLive ?
                                      CodexTaskTokens :
                                      CodexTaskLive;
            }
        }
    } else if(
        app->page == CodexPageUsage && (input->key == InputKeyUp || input->key == InputKeyDown)) {
        if(input->key == InputKeyDown) {
            app->usage_view = app->usage_view == CodexUsageTotal ?
                                  CodexUsageDaily :
                                  (CodexUsageView)(app->usage_view + 1);
        } else {
            app->usage_view = app->usage_view == CodexUsageDaily ?
                                  CodexUsageTotal :
                                  (CodexUsageView)(app->usage_view - 1);
        }
    } else if(
        app->page == CodexPageUsage && app->usage_view == CodexUsageDaily &&
        input->key == InputKeyOk) {
        app->usage_range_days =
            app->usage_range_days == 7 ? 14 : (app->usage_range_days == 14 ? 30 : 7);
    } else if(input->key == InputKeyLeft) {
        app->page = app->page == CodexPageQuota ? CodexPageLink : (CodexPage)(app->page - 1);
        if(app->page == CodexPageTasks) {
            app->tasks_view = CodexTasksOverview;
            if(app->model.task_count > 0) {
                app->selected_task_number =
                    app->model.tasks[app->selected_task].number;
            }
        }
    } else if(input->key == InputKeyRight) {
        app->page = app->page == CodexPageLink ? CodexPageQuota : (CodexPage)(app->page + 1);
        if(app->page == CodexPageTasks) {
            app->tasks_view = CodexTasksOverview;
            if(app->model.task_count > 0) {
                app->selected_task_number =
                    app->model.tasks[app->selected_task].number;
            }
        }
    }
    furi_mutex_release(app->mutex);
    view_port_update(app->view_port);
    return true;
}

int32_t codex_monitor_app(void* p) {
    (void)p;
    CodexMonitorApp* app = malloc(sizeof(CodexMonitorApp));
    furi_check(app);
    memset(app, 0, sizeof(CodexMonitorApp));
    app->model.quota_remaining = -1;
    app->model.reset_hour = -1;
    app->model.reset_minute = -1;
    app->model.plan = 'U';
    app->model.activity = CodexActivityIdle;
    app->model.battery_percent = furi_hal_power_get_pct();
    app->page = CodexPageHome;
    app->usage_view = CodexUsageDaily;
    app->usage_range_days = 14;
    app->tasks_view = CodexTasksOverview;
    app->mutex = furi_mutex_alloc(FuriMutexTypeNormal);
    app->event_queue = furi_message_queue_alloc(8, sizeof(CodexEvent));
    app->view_port = view_port_alloc();
    app->notifications = furi_record_open(RECORD_NOTIFICATION);

    view_port_draw_callback_set(app->view_port, codex_monitor_draw, app);
    view_port_input_callback_set(app->view_port, codex_monitor_input, app);

    Gui* gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(gui, app->view_port, GuiLayerFullscreen);

    CliRegistry* cli = furi_record_open(RECORD_CLI);
    cli_registry_add_command(
        cli,
        "codexmon",
        CliCommandFlagParallelSafe | CliCommandFlagInsomniaSafe,
        codex_monitor_cli,
        app);
    cli_registry_add_command(
        cli,
        "codexuse",
        CliCommandFlagParallelSafe | CliCommandFlagInsomniaSafe,
        codex_monitor_usage_cli,
        app);
    cli_registry_add_command(
        cli,
        "codextasks",
        CliCommandFlagParallelSafe | CliCommandFlagInsomniaSafe,
        codex_monitor_tasks_cli,
        app);
    cli_registry_add_command(
        cli,
        "codextask",
        CliCommandFlagParallelSafe | CliCommandFlagInsomniaSafe,
        codex_monitor_task_cli,
        app);

    app->bt = furi_record_open(RECORD_BT);
    bt_set_status_changed_callback(app->bt, codex_monitor_bt_status, app);
    app->ble_profile = bt_profile_start(app->bt, &codex_ble_profile_template, NULL);
    if(app->ble_profile) {
        furi_hal_bt_start_advertising();
    }

    bool running = true;
    while(running) {
        CodexEvent event;
        FuriStatus status =
            furi_message_queue_get(app->event_queue, &event, CODEX_LOOP_INTERVAL_MS);
        if(status == FuriStatusOk) {
            if(event.type == CodexEventInput) {
                running = codex_monitor_process_input_event(app, &event.data.input);
            } else if(event.type == CodexEventBtStatus) {
                bool connected = event.data.bt_status == BtStatusConnected;
                bool advertising = event.data.bt_status == BtStatusAdvertising;
                bool link_lost = false;
                furi_mutex_acquire(app->mutex, FuriWaitForever);
                app->model.ble_connected = connected;
                app->model.ble_advertising = advertising || connected;
                if(!connected && app->model.link == CodexLinkBle) {
                    app->model.connected = false;
                    app->model.link = CodexLinkNone;
                    app->model.link_since = 0;
                    app->model.activity = CodexActivityIdle;
                    app->model.active_turns = 0;
                    link_lost = true;
                }
                furi_mutex_release(app->mutex);
                if(link_lost) codex_monitor_led_off(app);
                if(connected && app->ble_profile) {
                    codex_ble_profile_set_callback(
                        app->ble_profile, CODEX_BLE_PACKET_MAX, codex_monitor_ble_event, app);
                }
            } else if(event.type == CodexEventBleData) {
                codex_monitor_process_ble(app, &event.data.ble_packet);
            }
        }

        uint32_t now = furi_get_tick();
        bool update_led = false;
        bool usb_lost = false;
        uint8_t led_phase = 0;
        bool battery_due = app->last_battery_tick == 0 ||
                           now - app->last_battery_tick >=
                               furi_ms_to_ticks(CODEX_BATTERY_INTERVAL_MS);
        uint8_t battery_percent = battery_due ? furi_hal_power_get_pct() : 0;
        furi_mutex_acquire(app->mutex, FuriWaitForever);
        if(battery_due) {
            app->model.battery_percent = battery_percent;
            app->last_battery_tick = now;
        }
        if(app->model.link == CodexLinkUsb) {
            if(furi_hal_power_get_usb_voltage() < CODEX_USB_DISCONNECT_VOLTAGE) {
                if(app->usb_low_samples < CODEX_USB_LOW_SAMPLES) app->usb_low_samples++;
                if(app->usb_low_samples >= CODEX_USB_LOW_SAMPLES) {
                    app->model.connected = false;
                    app->model.link = CodexLinkNone;
                    app->model.link_since = 0;
                    app->model.activity = CodexActivityIdle;
                    app->model.active_turns = 0;
                    app->usb_low_samples = 0;
                    usb_lost = true;
                }
            } else {
                app->usb_low_samples = 0;
            }
        } else {
            app->usb_low_samples = 0;
        }

        if(app->model.connected && app->model.activity == CodexActivityWorking) {
            if(app->last_led_tick == 0 ||
               now - app->last_led_tick >= furi_ms_to_ticks(CODEX_LOOP_INTERVAL_MS)) {
                led_phase = app->led_phase;
                app->led_phase = (app->led_phase + 1) % CODEX_LED_PHASES;
                app->last_led_tick = now;
                update_led = true;
            }
        }
        bool animate_activity =
            app->model.connected &&
            (app->model.activity == CodexActivityWorking ||
             (app->model.activity == CodexActivityDone &&
              app->model.animation_frame < CODEX_DONE_ANIMATION_FRAMES));
        if(animate_activity) {
            if(app->last_animation_tick == 0 ||
               now - app->last_animation_tick >=
                   furi_ms_to_ticks(CODEX_ACTIVITY_INTERVAL_MS)) {
                app->model.animation_frame++;
                app->last_animation_tick = now;
            }
        } else {
            app->last_animation_tick = 0;
        }
        furi_mutex_release(app->mutex);
        if(usb_lost) codex_monitor_led_off(app);
        if(update_led) codex_monitor_working_led(app, led_phase);
        view_port_update(app->view_port);
    }

    codex_monitor_led_off(app);
    bt_set_status_changed_callback(app->bt, NULL, NULL);
    if(app->ble_profile) {
        codex_ble_profile_set_callback(app->ble_profile, 0, NULL, NULL);
    }
    bt_disconnect(app->bt);
    bt_profile_restore_default(app->bt);
    furi_record_close(RECORD_BT);
    cli_registry_delete_command(cli, "codexmon");
    cli_registry_delete_command(cli, "codexuse");
    cli_registry_delete_command(cli, "codextasks");
    cli_registry_delete_command(cli, "codextask");
    furi_record_close(RECORD_CLI);
    gui_remove_view_port(gui, app->view_port);
    furi_record_close(RECORD_GUI);
    furi_record_close(RECORD_NOTIFICATION);
    view_port_free(app->view_port);
    furi_message_queue_free(app->event_queue);
    furi_mutex_free(app->mutex);
    free(app);
    return 0;
}
