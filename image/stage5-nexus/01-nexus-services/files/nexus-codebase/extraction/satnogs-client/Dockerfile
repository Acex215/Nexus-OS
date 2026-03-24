# SatNOGS Client image
#
# Copyright (C) 2022-2025 Libre Space Foundation <https://libre.space/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

ARG GNURADIO_IMAGE_TAG=3.10.5.1-satnogs
FROM librespace/gnuradio:${GNURADIO_IMAGE_TAG}
LABEL org.opencontainers.image.authors='SatNOGS project <dev@satnogs.org>'

ARG SATNOGS_CLIENT_UID=500
ARG SATNOGS_CLIENT_VARSTATEDIR=/var/lib/satnogs-client

# Disable pip cache
ARG PIP_NO_CACHE_DIR=true

# Disable Python compilation to bytecode
ENV PYTHONDONTWRITEBYTECODE=1

# Disable output buffering
ENV PYTHONUNBUFFERED=1

# Add unprivileged system user
RUN groupadd -r -g ${SATNOGS_CLIENT_UID} satnogs-client \
	&& useradd -l -r -u ${SATNOGS_CLIENT_UID} \
		-g satnogs-client \
		-d ${SATNOGS_CLIENT_VARSTATEDIR} \
		-s /bin/false \
		-G audio,dialout,plugdev \
		satnogs-client

# Create application varstate directory
RUN install -d -m 1777 -o ${SATNOGS_CLIENT_UID} -g ${SATNOGS_CLIENT_UID} ${SATNOGS_CLIENT_VARSTATEDIR}

# Copy source code
COPY . /usr/local/src/satnogs-client/

# Install system packages
RUN apt-get update \
	&& xargs -a /usr/local/src/satnogs-client/packages.debian apt-get install -qy pipx \
	&& rm -r /var/lib/apt/lists/*

# Install Python dependencies and application
RUN echo "[global]" > /etc/pip.conf \
	&& echo "extra-index-url=https://www.piwheels.org/simple" >> /etc/pip.conf \
	&& PIPX_HOME=/opt/pipx \
		PIPX_BIN_DIR=/usr/local/bin \
		PIPX_MAN_DIR=/usr/local/share/man \
		pipx install \
		--system-site-packages \
		--pip-args="--only-binary :all: -c /usr/local/src/satnogs-client/constraints.txt" \
		/usr/local/src/satnogs-client

CMD ["satnogs-client"]
