/************************************************************************

    ld-decode-shared_global.h

    ld-decode-tools shared library
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-decode-tools is free software: you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

************************************************************************/

#ifndef LDDECODESHARED_GLOBAL_H
#define LDDECODESHARED_GLOBAL_H

#include <QtCore/qglobal.h>

#if defined(LDDECODESHARED_LIBRARY)
#  define LDDECODESHAREDSHARED_EXPORT Q_DECL_EXPORT
#else
#  define LDDECODESHAREDSHARED_EXPORT Q_DECL_IMPORT
#endif

#endif // LDDECODESHARED_GLOBAL_H
