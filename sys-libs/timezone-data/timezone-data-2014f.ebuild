# Distributed under the terms of the GNU General Public License v2

EAPI="5"

inherit eutils toolchain-funcs flag-o-matic

code_ver=${PV}
data_ver=${PV}
DESCRIPTION="Timezone data (/usr/share/zoneinfo) and utilities (tzselect/zic/zdump)"
HOMEPAGE="http://www.iana.org/time-zones http://www.twinsun.com/tz/tz-link.htm"
SRC_URI="http://www.iana.org/time-zones/repository/releases/tzdata${data_ver}.tar.gz
	http://www.iana.org/time-zones/repository/releases/tzcode${code_ver}.tar.gz
	ftp://munnari.oz.au/pub/oldtz/tzdata${data_ver}.tar.gz
	ftp://munnari.oz.au/pub/oldtz/tzcode${data_ver}.tar.gz"

LICENSE="BSD public-domain"
SLOT="0"
KEYWORDS="~*"
IUSE="nls right_timezone elibc_FreeBSD elibc_glibc"

RDEPEND="!<sys-libs/glibc-2.3.5"

S=${WORKDIR}

src_prepare() {
	epatch "${FILESDIR}"/${PN}-2014f-makefile.patch
	tc-is-cross-compiler && cp -pR "${S}" "${S}"-native
}

_emake() {
	emake \
		TOPDIR="${EPREFIX}/usr" \
		REDO=$(usex right_timezone posix_right posix_only) \
		"$@"
}

src_compile() {
	local LDLIBS
	tc-export CC
	if use elibc_FreeBSD || use elibc_Darwin ; then
		append-cppflags -DSTD_INSPIRED #138251
	fi
	export NLS=$(usex nls 1 0)
	if use nls && ! use elibc_glibc ; then
		LDLIBS+=" -lintl" #154181
	fi
	# TOPDIR is used in some utils when compiling.
	_emake \
		AR="$(tc-getAR)" \
		CC="$(tc-getCC)" \
		RANLIB="$(tc-getRANLIB)" \
		CFLAGS="${CPPFLAGS} ${CFLAGS} -std=gnu99" \
		LDFLAGS="${LDFLAGS}" \
		LDLIBS="${LDLIBS}"
	if tc-is-cross-compiler ; then
		_emake -C "${S}"-native \
			CC="$(tc-getBUILD_CC)" \
			CFLAGS="${BUILD_CFLAGS}" \
			LDFLAGS="${BUILD_LDFLAGS}" \
			LDLIBS="${LDLIBS}" \
			zic
	fi
}

src_install() {
	local zic=""
	tc-is-cross-compiler && zic="zic=${S}-native/zic"
	_emake install ${zic} DESTDIR="${D}"
	dodoc README Theory
	dohtml *.htm

	# install the symlink by hand to not break existing timezones
	if ! use right_timezone && [[ ! -e ${ED}/usr/share/zoneinfo/posix ]] ; then
		dosym . /usr/share/zoneinfo/posix
	fi
}

get_TIMEZONE() {
	local tz src="${EROOT}etc/timezone"
	if [[ -e ${src} ]] ; then
		tz=$(sed -e 's:#.*::' -e 's:[[:space:]]*::g' -e '/^$/d' "${src}")
	else
		tz="FOOKABLOIE"
	fi
	[[ -z ${tz} ]] && return 1 || echo "${tz}"
}

pkg_preinst() {
	local tz=$(get_TIMEZONE)
	if ! use right_timezone && [[ ${tz} == right/* ]] ; then
		eerror "Your timezone is set to '${tz}' but you have USE=-right_timezone."
		die "Please fix your USE or timezone"
	fi
}

pkg_config() {
	# make sure the /etc/localtime file does not get stale #127899
	local tz src="${EROOT}etc/timezone" etc_lt="${EROOT}etc/localtime"

	tz=$(get_TIMEZONE) || return 0
	if [[ ${tz} == "FOOKABLOIE" ]] ; then
		elog "You do not have TIMEZONE set in ${src}."

		if [[ ! -e ${etc_lt} ]] ; then
			# if /etc/localtime is a symlink somewhere, assume they
			# know what they're doing and they're managing it themselves
			if [[ ! -L ${etc_lt} ]] ; then
				cp -f "${EROOT}"/usr/share/zoneinfo/Factory "${etc_lt}"
				elog "Setting ${etc_lt} to Factory."
			else
				elog "Assuming your ${etc_lt} symlink is what you want; skipping update."
			fi
		else
			elog "Skipping auto-update of ${etc_lt}."
		fi
		return 0
	fi

	if [[ ! -e ${EROOT}/usr/share/zoneinfo/${tz} ]] ; then
		elog "You have an invalid TIMEZONE setting in ${src}"
		elog "Your ${etc_lt} has been reset to Factory; enjoy!"
		tz="Factory"
	fi
	einfo "Updating ${etc_lt} with ${EROOT}usr/share/zoneinfo/${tz}"
	[[ -L ${etc_lt} ]] && rm -f "${etc_lt}"
	cp -f "${EROOT}"/usr/share/zoneinfo/"${tz}" "${etc_lt}"
}

pkg_postinst() {
	pkg_config
}