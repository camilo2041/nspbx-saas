# FreeSWITCH 1.10 compilado desde fuente (Debian) + mod_audio_fork.
#
# La imagen anterior (safarov/freeswitch:latest) es FROM scratch: un tarball
# precompilado sin toolchain ni headers, así que era imposible agregarle
# mod_audio_fork (necesario para streaming de audio en tiempo real hacia el
# voizbot IA). El repo apt oficial de SignalWire requiere un token de
# registro por dominio, poco práctico para un build de Docker reproducible;
# por eso se compila FreeSWITCH desde el código fuente oficial.
#
# Stage 1: compila FreeSWITCH + mod_audio_fork con el toolchain completo.
# Stage 2: runtime limpio, sin compiladores ni fuentes, solo los binarios,
# módulos y sonidos ya instalados.

FROM debian:bookworm-slim AS build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential autoconf automake libtool libtool-bin pkg-config cmake git ca-certificates \
    libssl-dev zlib1g-dev libcurl4-openssl-dev libpcre2-dev libpcre3-dev libsqlite3-dev \
    libedit-dev libspeex-dev libspeexdsp-dev libldns-dev libavformat-dev \
    libswscale-dev libopus-dev libsndfile1-dev \
    libpq-dev unixodbc-dev libyaml-dev libjpeg-dev python3-dev \
    yasm nasm libtiff-dev libpng-dev libavcodec-dev libswresample-dev \
    libevent-dev libwebsockets-dev uuid-dev libspandsp-dev flite1-dev \
    glib2.0-dev liblua5.3-dev \
    libshout3-dev libmp3lame-dev libogg-dev libvorbis-dev \
    && rm -rf /var/lib/apt/lists/*

ARG FREESWITCH_REF=v1.10.12
# (DRACHTIO_MODULES_REF se declara más abajo, justo antes de usarse:
#  un ARG invalida la caché de TODAS las capas siguientes, así que
#  declararlo acá arriba obligaba a recompilar FreeSWITCH entero —
#  ~40 minutos— cada vez que se tocaba la versión del módulo.)

# --- FreeSWITCH: mismos módulos que ya carga freeswitch/conf/autoload_configs
# (mod_signalwire, mod_sofia, mod_esl, mod_xml_curl, mod_pgsql, mod_flite,
# mod_callcenter, mod_lua, mod_av, mod_opus, mod_spandsp, mod_amr, mod_g729,
# etc.) para que la config montada siga funcionando sin cambios.
# sofia-sip: Debian solo trae 1.12.11 y FreeSWITCH 1.10 exige >= 1.13.17 —
# se compila desde el fork que mantiene el propio proyecto FreeSWITCH.
ARG SOFIA_SIP_REF=v1.13.18
RUN git clone --depth 1 --branch ${SOFIA_SIP_REF} https://github.com/freeswitch/sofia-sip.git /usr/src/sofia-sip
WORKDIR /usr/src/sofia-sip
RUN ./bootstrap.sh && ./configure --disable-tests && make -j"$(nproc)" && make install && ldconfig

# libks: librería de SignalWire que necesita mod_verto (softphone WebRTC del
# navegador), tampoco empaquetada en Debian.
ARG LIBKS_REF=v2.0.3
RUN git clone --branch ${LIBKS_REF} https://github.com/signalwire/libks.git /usr/src/libks
WORKDIR /usr/src/libks
RUN cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local . && make -j"$(nproc)" && make install && ldconfig

# El paquete libspandsp-dev de Debian trae la librería spandsp 3.x real,
# pero su .pc declara "Version: 0.0.6" (versionado propio de Debian, no el
# de la API) — el ./configure de FreeSWITCH exige spandsp >= 3.0 y rechaza
# el paquete por ese numerito, aunque la librería instalada sí sirve.
RUN sed -i 's/^Version:.*/Version: 3.0.0/' /usr/lib/x86_64-linux-gnu/pkgconfig/spandsp.pc

RUN git clone --depth 1 --branch ${FREESWITCH_REF} https://github.com/signalwire/freeswitch.git /usr/src/freeswitch
WORKDIR /usr/src/freeswitch
RUN ./bootstrap.sh -j
# `configure` decide contra qué librerías de módulos opcionales chequear
# leyendo el archivo `modules.conf` de la raíz (bootstrap.sh lo genera
# copiando build/modules.conf.in) — el sed tiene que ir sobre ESE archivo,
# después de bootstrap.sh y antes de configure. mod_pgsql y los códecs
# patentados (g729/amr) no vienen habilitados por defecto pero la config
# actual sí los espera cargados; mod_signalwire (conector a la nube de
# SignalWire) se deshabilita porque este PBX es self-hosted y evita tener
# que compilar signalwire-client-c.
RUN sed -i \
    -e 's/^#applications\/mod_callcenter/applications\/mod_callcenter/' \
    -e 's/^#codecs\/mod_g729/codecs\/mod_g729/' \
    -e 's/^#codecs\/mod_amr$/codecs\/mod_amr/' \
    -e 's/^#databases\/mod_pgsql/databases\/mod_pgsql/' \
    -e 's/^#applications\/mod_esl/applications\/mod_esl/' \
    -e 's/^#asr_tts\/mod_flite/asr_tts\/mod_flite/' \
    -e 's/^#event_handlers\/mod_json_cdr/event_handlers\/mod_json_cdr/' \
    -e 's/^#formats\/mod_shout/formats\/mod_shout/' \
    -e 's/^#say\/mod_say_es$/say\/mod_say_es/' \
    -e 's/^#xml_int\/mod_xml_curl/xml_int\/mod_xml_curl/' \
    -e 's/^applications\/mod_signalwire/#applications\/mod_signalwire/' \
    -e 's/^applications\/mod_spandsp$/#applications\/mod_spandsp/' \
    modules.conf
# --sysconfdir/--localstatedir/--datadir alineados a las rutas que ya usa
# docker-compose.yml (./freeswitch/conf:/etc/freeswitch,
# ./freeswitch/sounds:/usr/share/freeswitch/sounds,
# ./freeswitch/recordings:/var/lib/freeswitch/recordings) para no tener que
# tocar esos volúmenes ni el código del backend que asume esas rutas.
RUN ./configure \
    --sysconfdir=/etc/freeswitch \
    --localstatedir=/var/lib/freeswitch \
    --datadir=/usr/share \
    --enable-core-pgsql-support
RUN make -j"$(nproc)"
RUN make install
# Los sonidos de stock ("callie" en inglés) no hacen falta: el volumen
# ./freeswitch/sounds:/usr/share/freeswitch/sounds del compose los
# reemplaza por completo con los sonidos propios del proyecto.

# --- mod_audio_fork: streaming de audio del canal por websocket, la pieza
# que faltaba para que el voizbot IA sea en tiempo real (ver
# backend/app/services/ai_agent.py). El módulo trae un Makefile.am pensado
# para vivir DENTRO del árbol fuente de FreeSWITCH (usa
# $(top_srcdir)/build/modmake.rulesam), no un build standalone — en vez de
# reestructurar el árbol ya compilado, se linkea a mano contra la
# instalación de FreeSWITCH ya hecha arriba vía `pkg-config freeswitch`
# (interfaz pensada justo para compilar módulos de terceros así).
# Commit fijo, NO la rama "main": con una rama móvil, reconstruir esta
# imagen dentro de seis meses podía traer otro mod_audio_fork y dejar
# sin audio al voizbot sin que nadie hubiera tocado una línea del
# proyecto. Este es el HEAD de main del 2024-03-07 ("update readme"),
# que es el que ya está compilado y funcionando en producción.
# Para actualizarlo a propósito: cambiar el SHA y reconstruir.
ARG DRACHTIO_MODULES_REF=88e1465908a89bed5c95d336aa53a3899bb5abb5

# `git clone --branch` NO acepta un SHA (solo rama o tag), así que se
# trae el commit puntual con un fetch superficial: mismo peso de
# descarga que el clone --depth 1 anterior, pero reproducible.
RUN mkdir -p /usr/src/drachtio-modules \
    && cd /usr/src/drachtio-modules \
    && git init -q . \
    && git remote add origin https://github.com/mdslaney/drachtio-freeswitch-modules.git \
    && git fetch --depth 1 origin ${DRACHTIO_MODULES_REF} \
    && git checkout -q FETCH_HEAD
WORKDIR /usr/src/drachtio-modules/modules/mod_audio_fork
ENV PKG_CONFIG_PATH=/usr/local/freeswitch/lib/pkgconfig:/usr/local/lib/pkgconfig
RUN pkg-config --exists freeswitch && echo "freeswitch.pc OK" \
    && pkg-config --cflags freeswitch \
    && pkg-config --variable=modulesdir freeswitch
RUN g++ -std=c++11 -fPIC -c $(pkg-config --cflags freeswitch) lws_glue.cpp parser.cpp audio_pipe.cpp \
    && gcc -fPIC -c $(pkg-config --cflags freeswitch) mod_audio_fork.c \
    && g++ -shared -o mod_audio_fork.so mod_audio_fork.o lws_glue.o parser.o audio_pipe.o \
       $(pkg-config --libs freeswitch) $(pkg-config --libs libwebsockets) \
    && install -m755 mod_audio_fork.so "$(pkg-config --variable=modulesdir freeswitch)/"

# /etc, /usr/share/freeswitch y /var/lib/freeswitch se montan por volumen en
# docker-compose.yml (su contenido real viene de ahí, no de la imagen), pero
# tienen que existir para que el COPY del stage final no falle — `make
# install` no siempre los crea si quedan vacíos (p.ej. no instalamos los
# sonidos de stock).
RUN mkdir -p /etc/freeswitch /usr/share/freeswitch /var/lib/freeswitch


FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 libcurl4 libpcre2-8-0 libpcre3 libsqlite3-0 libedit2 libspeex1 libspeexdsp1 \
    libldns3 libavformat59 libswscale6 libopus0 libsndfile1 libpq5 \
    unixodbc libyaml-0-2 libjpeg62-turbo libtiff6 libpng16-16 \
    libavcodec59 libswresample4 libevent-2.1-7 libwebsockets17 \
    liblua5.3-0 libflite1 libspandsp2 \
    libshout3 libmp3lame0 libogg0 libvorbis0a libvorbisenc2 \
    tini curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/freeswitch /usr/local/freeswitch
COPY --from=build /etc/freeswitch /etc/freeswitch
COPY --from=build /usr/share/freeswitch /usr/share/freeswitch
COPY --from=build /var/lib/freeswitch /var/lib/freeswitch
# sofia-sip y libks se compilaron desde fuente con prefix=/usr/local (no
# vienen de un paquete apt), así que sus .so también hay que traerlos.
COPY --from=build /usr/local/lib /usr/local/lib
COPY --from=build /usr/local/include /usr/local/include
RUN ldconfig

ENV PATH=/usr/local/freeswitch/bin:$PATH

# FreeSWITCH corre como `freeswitch` (uid 10001, el mismo del backend: ver
# entrypoint.sh). Las carpetas donde escribe y que viven dentro de la imagen
# se crean acá con ese dueño; las montadas las ajusta el entrypoint.
RUN groupadd --system --gid 10001 freeswitch \
    && useradd --system --uid 10001 --gid freeswitch --no-create-home --shell /usr/sbin/nologin freeswitch \
    && mkdir -p /var/lib/freeswitch/db /var/lib/freeswitch/storage /var/lib/freeswitch/cache \
        /var/lib/freeswitch/recordings /var/log/freeswitch /var/run/freeswitch /usr/local/freeswitch/certs \
    && chown -R freeswitch:freeswitch /var/lib/freeswitch /var/log/freeswitch /var/run/freeswitch \
        /usr/local/freeswitch/certs
COPY entrypoint.sh /usr/local/bin/nspbx-entrypoint.sh

EXPOSE 5060/udp 5060/tcp 5080/udp 8021 5066 7443
EXPOSE 16384-16584/udp

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/nspbx-entrypoint.sh"]
# El binario NO respeta --sysconfdir/--localstatedir/--datadir de ./configure
# para su búsqueda de config en tiempo de ejecución (esos flags solo influyen
# en cómo `make install` coloca los archivos) — sin esto arrancaba leyendo
# los configs de EJEMPLO de /usr/local/freeswitch/conf (con listen-ip="::",
# de ahí "Cannot get information about IP address ::" en mod_event_socket)
# en vez de la config real montada. -conf/-recordings/-sounds fuerzan las
# rutas que ya usan docker-compose.yml y el backend.
#
# -u/-g: FreeSWITCH deja de ser root apenas arranca, antes de cargar
# módulos y abrir puertos (todos son > 1024). -run/-storage/-cache llevan a
# carpetas de ese usuario lo que antes caía en /usr/local/freeswitch, de root.
# -certs explícito: es donde se monta ./freeswitch/certs (wss.pem) y donde
# lo deja scripts/renovar-cert-wss.sh; antes dependía del prefijo de compilación.
CMD ["freeswitch", "-nonat", "-nc", "-nf", \
     "-u", "freeswitch", "-g", "freeswitch", \
     "-conf", "/etc/freeswitch", \
     "-log", "/var/log/freeswitch", \
     "-db", "/var/lib/freeswitch/db", \
     "-run", "/var/run/freeswitch", \
     "-storage", "/var/lib/freeswitch/storage", \
     "-cache", "/var/lib/freeswitch/cache", \
     "-certs", "/usr/local/freeswitch/certs", \
     "-recordings", "/var/lib/freeswitch/recordings", \
     "-sounds", "/usr/share/freeswitch/sounds"]
