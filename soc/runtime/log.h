#ifndef __LOG_H
#define __LOG_H

#include <stdarg.h>

#define LOG_BUFFER_SIZE 4096

void log_va(const char *fmt, va_list args);
void log(const char *fmt, ...);

void log_get(char *outbuf);

#endif /* __LOG_H */
