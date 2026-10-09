# Web-only PsyCross and Lain additions; see LICENSE and UPSTREAM.txt for licensing.
file(GLOB_RECURSE PSX_SRCS_C CONFIGURE_DEPENDS src/*.c src/*.C)
file(GLOB_RECURSE PSX_SRCS_CPP CONFIGURE_DEPENDS src/*.cpp)
set_source_files_properties(${PSX_SRCS_C} PROPERTIES LANGUAGE C)
set_source_files_properties(${PSX_SRCS_CPP} PROPERTIES LANGUAGE CXX)

add_library(psx STATIC ${PSX_SRCS_C} ${PSX_SRCS_CPP})
target_include_directories(psx PUBLIC include include/psx)
# The game uses integer 2D primitives; PGXP and half-float implementations are not bundled.
target_compile_definitions(psx PUBLIC USE_PGXP=0)
target_include_directories(psx BEFORE PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../compat)
target_compile_options(psx PRIVATE $<$<COMPILE_LANGUAGE:C>:-include assert.h>
                                   $<$<COMPILE_LANGUAGE:CXX>:-Wno-c++11-narrowing>)
target_compile_options(psx PUBLIC -pthread -sUSE_SDL=2)
target_link_options(psx PUBLIC -pthread -sUSE_SDL=2)
