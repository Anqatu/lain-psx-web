/* Minimal browser entry point for the native port (no PS1 emulator). */
#include <assert.h>
#include <emscripten.h>
#include <emscripten/html5_webgl.h>
#include <SDL.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "libcd.h"
#include "libetc.h"
#include "libgs.h"
#include "libmcrd.h"
#include "libspu.h"
#include "lain_xa.h"
#include "PsyX/PsyX_public.h"

#include "iso.h"
#include "psx_arena.h"
#include "psx_mem.h"

enum { WEB_MCRD_SIZE = 128 * 1024 };
enum { WEB_KEY_COUNT = 16 };

#define RAW_SECTOR 2352u
#define HTTP_CHUNK_SECTORS 512u
#define HTTP_CHUNK_BYTES (RAW_SECTOR * HTTP_CHUNK_SECTORS)
#define HTTP_CACHE_SLOTS 12

typedef struct {
    uint64_t index;
    uint64_t stamp;
    unsigned char *data;
    size_t bytes;
    int valid;
} HttpChunk;

typedef struct {
    int disc;
    uint64_t size;
    uint64_t stamp;
    char url[2048];
    SDL_mutex *mutex;
    HttpChunk chunks[HTTP_CACHE_SLOTS];
} HttpDisc;

static HttpDisc s_discs[2];
static int s_inserted_disc;
static _Atomic int s_configured;
static unsigned char s_pending_import[WEB_MCRD_SIZE];
static _Atomic int s_pending_import_state;

typedef struct {
    int width;
    int height;
    int render_scale;
    int bilinear;
    int interpolate;
    int volume;
    int keys[WEB_KEY_COUNT];
} WebSettings;

static WebSettings s_web_settings;
static WebSettings s_pending_settings;
static _Atomic int s_pending_settings_state;
static _Atomic int s_input_active;

extern int web_disc_fetch_range(const char *url, uint32_t start, uint32_t end,
                                void *out, int capacity);
extern void web_mcrd_import_complete(int success);

static void web_status(const char *text)
{
    MAIN_THREAD_EM_ASM({ Module['lainStatus']?.(UTF8ToString($0)); }, text);
}

static void web_failure(const char *key)
{
    MAIN_THREAD_EM_ASM({ Module['lainFailure']?.(UTF8ToString($0)); }, key);
}

static void web_started(void)
{
    MAIN_THREAD_EM_ASM({ Module['lainStarted']?.(); });
}

static int disc_read_at(void *user, uint64_t offset, void *out, size_t bytes)
{
    HttpDisc *disc = user;
    unsigned char *dst = out;
    if (!disc || offset > disc->size || bytes > disc->size - offset)
        return -1;

    SDL_LockMutex(disc->mutex);

    while (bytes > 0)
    {
        uint64_t chunk_index = offset / HTTP_CHUNK_BYTES;
        size_t chunk_offset = (size_t)(offset % HTTP_CHUNK_BYTES);
        HttpChunk *hit = NULL, *victim = &disc->chunks[0];
        for (int i = 0; i < HTTP_CACHE_SLOTS; i++)
        {
            HttpChunk *c = &disc->chunks[i];
            if (c->valid && c->index == chunk_index)
            {
                hit = c;
                break;
            }
            if (!c->valid || c->stamp < victim->stamp)
                victim = c;
        }
        if (!hit)
        {
            uint64_t start = chunk_index * HTTP_CHUNK_BYTES;
            uint64_t remain = disc->size - start;
            size_t want = remain < HTTP_CHUNK_BYTES ? (size_t)remain : HTTP_CHUNK_BYTES;
            if (!victim->data)
                victim->data = malloc(HTTP_CHUNK_BYTES);
            if (!victim->data)
                goto fail;
            int got = web_disc_fetch_range(disc->url, (uint32_t)start,
                                           (uint32_t)(start + want - 1),
                                           victim->data, HTTP_CHUNK_BYTES);
            if (got != (int)want)
                goto fail;
            victim->index = chunk_index;
            victim->bytes = want;
            victim->valid = 1;
            hit = victim;
        }
        hit->stamp = ++disc->stamp;
        size_t take = hit->bytes - chunk_offset;
        if (take > bytes)
            take = bytes;
        memcpy(dst, hit->data + chunk_offset, take);
        dst += take;
        offset += take;
        bytes -= take;
    }
    SDL_UnlockMutex(disc->mutex);
    return 0;

fail:
    SDL_UnlockMutex(disc->mutex);
    return -1;
}

static uint32_t le32(const unsigned char *p)
{
    return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static int identify_disc(HttpDisc *disc)
{
    IsoSource source = {disc_read_at, disc};
    unsigned char sec[2048];
    if (iso_source_read_sector(&source, 16, sec) != 0)
        return -1;
    if (memcmp(sec + 1, "CD001", 5) != 0)
        return -2;
    uint32_t root_lba = le32(sec + 158), root_size = le32(sec + 166);
    for (uint32_t s = 0; s < (root_size + 2047) / 2048; s++)
    {
        if (iso_source_read_sector(&source, root_lba + s, sec) != 0)
            return -3;
        for (int pos = 0; pos < 2048 && sec[pos]; pos += sec[pos])
        {
            const unsigned char *rec = sec + pos;
            int len = rec[32];
            if (len >= 10 && memcmp(rec + 33, "LAIN_1.INF", 10) == 0) return 1;
            if (len >= 10 && memcmp(rec + 33, "LAIN_2.INF", 10) == 0) return 2;
        }
    }
    return 0;
}

static void insert_disc(int index)
{
    PsyX_CDFS_SwapSource(disc_read_at, &s_discs[index], s_discs[index].size);
    LainCD_OpenShell(700);
    s_inserted_disc = index;
}

static void settings_defaults(WebSettings *settings)
{
    static const int keys[WEB_KEY_COUNT] = {
        SDL_SCANCODE_UP, SDL_SCANCODE_DOWN, SDL_SCANCODE_LEFT, SDL_SCANCODE_RIGHT,
        SDL_SCANCODE_C, SDL_SCANCODE_V, SDL_SCANCODE_X, SDL_SCANCODE_Z,
        SDL_SCANCODE_LSHIFT, SDL_SCANCODE_LCTRL, SDL_SCANCODE_LEFTBRACKET,
        SDL_SCANCODE_RSHIFT, SDL_SCANCODE_RCTRL, SDL_SCANCODE_RIGHTBRACKET,
        SDL_SCANCODE_RETURN, SDL_SCANCODE_SPACE,
    };
    memset(settings, 0, sizeof *settings);
    settings->width = 960;
    settings->height = 720;
    settings->volume = 100;
    memcpy(settings->keys, keys, sizeof keys);
}

static void apply_keymap(const WebSettings *settings)
{
    int *dest[WEB_KEY_COUNT] = {
        &g_cfg_keyboardMapping.kc_dpad_up,
        &g_cfg_keyboardMapping.kc_dpad_down,
        &g_cfg_keyboardMapping.kc_dpad_left,
        &g_cfg_keyboardMapping.kc_dpad_right,
        &g_cfg_keyboardMapping.kc_cross,
        &g_cfg_keyboardMapping.kc_circle,
        &g_cfg_keyboardMapping.kc_square,
        &g_cfg_keyboardMapping.kc_triangle,
        &g_cfg_keyboardMapping.kc_l1,
        &g_cfg_keyboardMapping.kc_l2,
        &g_cfg_keyboardMapping.kc_l3,
        &g_cfg_keyboardMapping.kc_r1,
        &g_cfg_keyboardMapping.kc_r2,
        &g_cfg_keyboardMapping.kc_r3,
        &g_cfg_keyboardMapping.kc_start,
        &g_cfg_keyboardMapping.kc_select,
    };
    for (int i = 0; i < WEB_KEY_COUNT; i++)
        *dest[i] = settings->keys[i];
}

static int take_pending_settings(WebSettings *settings)
{
    int expected = 1;
    if (!atomic_compare_exchange_strong_explicit(&s_pending_settings_state, &expected, 2,
                                                 memory_order_acq_rel, memory_order_acquire))
        return 0;
    *settings = s_pending_settings;
    atomic_store_explicit(&s_pending_settings_state, 0, memory_order_release);
    return 1;
}

static void apply_settings(const WebSettings *settings, int resize)
{
    if (resize && (settings->width != s_web_settings.width || settings->height != s_web_settings.height))
        PsyX_Web_SetWindowSize(settings->width, settings->height);
    g_cfg_renderScale = settings->render_scale;
    g_cfg_bilinearFiltering = settings->bilinear;
    g_cfg_interpolate = settings->interpolate;
    LainSpu_SetOutputGain(settings->volume / 100.0f);
    apply_keymap(settings);
    s_web_settings = *settings;
}

static void on_begin_scene(void)
{
    g_lain_padBlocked = !atomic_load_explicit(&s_input_active, memory_order_acquire);
    WebSettings settings;
    if (take_pending_settings(&settings))
        apply_settings(&settings, 1);
}

extern short g_current_site;
static void on_end_scene(void)
{
    if ((g_current_site == 0 || g_current_site == 1) && g_current_site != s_inserted_disc)
        insert_disc(g_current_site);
    if (atomic_load_explicit(&s_pending_import_state, memory_order_acquire) == 1 && LainMcrd_CanReplace(0))
    {
        int success = LainMcrd_ReplaceRaw(0, s_pending_import, sizeof s_pending_import);
        atomic_store_explicit(&s_pending_import_state, 0, memory_order_release);
        web_mcrd_import_complete(success);
    }
    g_lain_padBlocked = !atomic_load_explicit(&s_input_active, memory_order_acquire);
    PsyX_UpdateInput();
}

EMSCRIPTEN_KEEPALIVE void lain_web_set_input_active(int active)
{
    /* Reset on the DOM event thread to prevent stuck keys after a focus change. */
    if (!active)
    {
        SDL_ResetKeyboard();
        SDL_SetModState(KMOD_NONE);
    }
    atomic_store_explicit(&s_input_active, active != 0, memory_order_release);
}

EMSCRIPTEN_KEEPALIVE int lain_web_queue_import(const void *data, int size)
{
    int expected = 0;
    if (!data || size != (int)sizeof s_pending_import ||
        !atomic_compare_exchange_strong_explicit(&s_pending_import_state, &expected, 2,
                                                 memory_order_acq_rel, memory_order_acquire))
        return 0;
    memcpy(s_pending_import, data, sizeof s_pending_import);
    atomic_store_explicit(&s_pending_import_state, 1, memory_order_release);
    return 1;
}

EMSCRIPTEN_KEEPALIVE int lain_web_queue_settings(int width, int height, int render_scale,
                                                 int bilinear, int interpolate, int volume,
                                                 const int *keys, int key_count)
{
    int expected = 0;
    if (width < 320 || width > 3840 || height < 240 || height > 2160 ||
        render_scale < 0 || render_scale > 8 || !keys || key_count != WEB_KEY_COUNT ||
        volume < 0 || volume > 100 ||
        !atomic_compare_exchange_strong_explicit(&s_pending_settings_state, &expected, 2,
                                                 memory_order_acq_rel, memory_order_acquire))
        return 0;

    s_pending_settings.width = width;
    s_pending_settings.height = height;
    s_pending_settings.render_scale = render_scale;
    s_pending_settings.bilinear = bilinear != 0;
    s_pending_settings.interpolate = interpolate != 0;
    s_pending_settings.volume = volume;
    for (int i = 0; i < WEB_KEY_COUNT; i++)
    {
        if (keys[i] < SDL_SCANCODE_UNKNOWN || keys[i] >= SDL_NUM_SCANCODES)
        {
            atomic_store_explicit(&s_pending_settings_state, 0, memory_order_release);
            return 0;
        }
        s_pending_settings.keys[i] = keys[i];
    }
    atomic_store_explicit(&s_pending_settings_state, 1, memory_order_release);
    return 1;
}

EMSCRIPTEN_KEEPALIVE int lain_web_configure(const char *disc1_url, uint32_t disc1_size,
                                            const char *disc2_url, uint32_t disc2_size)
{
    if (!disc1_url || !disc1_url[0] || !disc2_url || !disc2_url[0] ||
        !disc1_size || !disc2_size || disc1_size % RAW_SECTOR || disc2_size % RAW_SECTOR)
        return 0;

    memset(s_discs, 0, sizeof s_discs);
    s_discs[0].disc = 0;
    s_discs[1].disc = 1;
    s_discs[0].size = disc1_size;
    s_discs[1].size = disc2_size;
    snprintf(s_discs[0].url, sizeof s_discs[0].url, "%s", disc1_url);
    snprintf(s_discs[1].url, sizeof s_discs[1].url, "%s", disc2_url);
    atomic_store_explicit(&s_configured, 1, memory_order_release);
    return 1;
}

EMSCRIPTEN_KEEPALIVE int lain_web_prepare(int width, int height)
{
    if (!PsyX_Web_PrepareWindow("Serial Experiments Lain", width, height))
        return 0;
    /* Keep SDL key state updates; let the Web UI manage default actions and shortcuts. */
    SDL_EventState(SDL_KEYDOWN, SDL_DISABLE);
    SDL_EventState(SDL_KEYUP, SDL_DISABLE);
    SDL_StopTextInput();
    if (!LainSpu_PrepareOutput())
        LainSpu_SetOutputEnabled(0);
    return 1;
}

int port_data_relocate(void);
int lain_game_main(void);

EMSCRIPTEN_KEEPALIVE int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    if (!atomic_load_explicit(&s_configured, memory_order_acquire))
    {
        web_failure("boot.missingConfig");
        return 1;
    }
    settings_defaults(&s_web_settings);
    WebSettings initial_settings;
    if (take_pending_settings(&initial_settings))
        s_web_settings = initial_settings;
    if (SDL_Init(SDL_INIT_TIMER | SDL_INIT_EVENTS) != 0)
    {
        web_failure("boot.sdlFailed");
        return 1;
    }
    s_discs[0].mutex = SDL_CreateMutex();
    s_discs[1].mutex = SDL_CreateMutex();
    if (!s_discs[0].mutex || !s_discs[1].mutex)
    {
        web_failure("boot.cacheFailed");
        return 1;
    }
    int disc1_id = identify_disc(&s_discs[0]);
    int disc2_id = identify_disc(&s_discs[1]);
    if (disc1_id != 1 || disc2_id != 2)
    {
        MAIN_THREAD_EM_ASM({
            Module['lainFailure']?.('boot.discVerification', { disc1: $0, disc2: $1 });
        }, disc1_id, disc2_id);
        return 1;
    }

    web_status("boot.loadingExecutable");
    IsoSource source = {disc_read_at, &s_discs[0]};
    char error[256];
    if (psx_mem_load_source(&source, error, sizeof error) != 0)
    {
        MAIN_THREAD_EM_ASM({
            Module['lainLoadFailed']?.(UTF8ToString($0));
        }, error);
        return 1;
    }
    web_status("boot.relocating");
    if (port_data_relocate() != 0)
    {
        web_failure("boot.relocationFailed");
        return 1;
    }

    g_cfg_renderScale = s_web_settings.render_scale;
    g_cfg_bilinearFiltering = s_web_settings.bilinear;
    g_cfg_interpolate = s_web_settings.interpolate;
    g_cfg_swapInterval = 0;
    web_status("boot.initializingGraphics");
    PsyX_Initialise("Serial Experiments Lain", s_web_settings.width, s_web_settings.height, 0);
    if (!emscripten_webgl_get_current_context())
    {
        web_failure("boot.webglFailed");
        return 1;
    }
    PsyX_SetSwapInterval(0);
    PsyX_EnableSwapInterval(0);
    apply_keymap(&s_web_settings);
    LainSpu_SetOutputGain(s_web_settings.volume / 100.0f);
    GsSetMapBase(psx_arena, PSX_ARENA_SIZE, PSX_RAM_BASE);
    web_status("boot.initializingCard");
    PsyX_CDFS_Init_Source(disc_read_at, &s_discs[0], s_discs[0].size, 0, RAW_SECTOR);
    s_inserted_disc = 0;
    LainMcrd_SetCardPath(0, "/persist/memcard1.mcd");
    g_lain_padBlocked = 1;
    g_lain_onBeginScene = on_begin_scene;
    g_lain_onEndScene = on_end_scene;
    atexit(LainCD_Shutdown);
    web_started();
    web_status("boot.running");
    lain_game_main();
    return 0;
}
