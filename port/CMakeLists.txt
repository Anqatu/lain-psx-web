# Standalone packaging of the upstream Web target; see ../README.md for changes.
cmake_minimum_required(VERSION 3.20)
project(lain_browser LANGUAGES C CXX)

if(NOT EMSCRIPTEN)
    message(FATAL_ERROR "Use python port/web/build_web.py from an Emscripten environment")
endif()
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)

# build_web.py embeds translations into the HTML; do not use the raw shell.html.
set(LAIN_WEB_SHELL "${CMAKE_CURRENT_BINARY_DIR}/shell.html" CACHE FILEPATH "Preprocessed Web HTML")
if(NOT EXISTS "${LAIN_WEB_SHELL}")
    message(FATAL_ERROR "Preprocessed HTML is missing. Run python port/web/build_web.py")
endif()

add_subdirectory(psx)
add_library(psx_arena STATIC game/generated/psx_arena_web.c)
target_compile_options(psx_arena PRIVATE -pthread)

file(GLOB GAME_SRCS CONFIGURE_DEPENDS game/*.c)
set(HOOKS_DIR ${CMAKE_CURRENT_BINARY_DIR}/hooks)
set(GAME_HOOKED_SRCS ${HOOKS_DIR}/game_hooks.c)
foreach(src ${GAME_SRCS})
    get_filename_component(name ${src} NAME)
    list(APPEND GAME_HOOKED_SRCS ${HOOKS_DIR}/game/${name})
endforeach()
add_custom_command(OUTPUT ${GAME_HOOKED_SRCS}
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/gen_hooks.py" "${HOOKS_DIR}"
    DEPENDS ${GAME_SRCS} tools/gen_hooks.py game/include/game_protos.h game/generated/symbols.txt game/PORT_TYPES.md
    COMMENT "Generating game function hooks"
    VERBATIM)
add_library(game STATIC ${GAME_HOOKED_SRCS})
target_include_directories(game PUBLIC game/include)
target_compile_definitions(game PRIVATE NON_MATCHING NEEDS_RODATA NEEDS_SDATA)
target_compile_options(game PUBLIC -pthread -sUSE_SDL=2)
target_link_options(game PUBLIC -pthread -sUSE_SDL=2)
target_link_libraries(game PUBLIC psx)
set_source_files_properties(${HOOKS_DIR}/game/80013138.c PROPERTIES COMPILE_DEFINITIONS main=lain_game_main)

add_library(client_web STATIC client/iso.c client/psx_mem.c)
target_include_directories(client_web PUBLIC client game/include)
target_compile_options(client_web PUBLIC -pthread -sUSE_SDL=2)
target_link_options(client_web PUBLIC -pthread -sUSE_SDL=2)

add_executable(lain_web src/web_main.c src/platform.c src/sdk_extra.c)
target_link_libraries(lain_web PRIVATE client_web game psx psx_arena)
target_compile_options(lain_web PRIVATE -pthread -sUSE_SDL=2)
target_link_options(lain_web PRIVATE
    -pthread
    -sUSE_SDL=2
    -sPROXY_TO_PTHREAD=1
    -sPTHREAD_POOL_SIZE=4
    -sOFFSCREEN_FRAMEBUFFER=1
    -sMIN_WEBGL_VERSION=2
    -sMAX_WEBGL_VERSION=2
    -sFULL_ES3=1
    -sFORCE_FILESYSTEM=1
    -sEXIT_RUNTIME=1
    -sALLOW_MEMORY_GROWTH=1
    -sINITIAL_MEMORY=268435456
    -sSTACK_SIZE=4194304
    -sDEFAULT_PTHREAD_STACK_SIZE=2097152
    -sEXPORTED_FUNCTIONS=['_main','_malloc','_free','_lain_web_configure','_lain_web_prepare','_lain_web_queue_import','_lain_web_queue_settings','_lain_web_set_input_active']
    -sEXPORTED_RUNTIME_METHODS=['FS','callMain']
    --shell-file ${LAIN_WEB_SHELL}
    --pre-js ${CMAKE_CURRENT_SOURCE_DIR}/web/pre.js
    --js-library ${CMAKE_CURRENT_SOURCE_DIR}/web/library.js
    -lidbfs.js)
set_target_properties(lain_web PROPERTIES OUTPUT_NAME index SUFFIX ".html")
set_property(TARGET lain_web PROPERTY LINK_DEPENDS
    "${LAIN_WEB_SHELL};${CMAKE_CURRENT_SOURCE_DIR}/web/pre.js;${CMAKE_CURRENT_SOURCE_DIR}/web/library.js")
