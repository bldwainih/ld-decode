/************************************************************************

    f2frame.h

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#ifndef F2FRAME_H
#define F2FRAME_H

#include <QCoreApplication>
#include <QDebug>

#include "f3frame.h"

class F2Frame
{
public:
    F2Frame();

    void setData(QByteArray dataParam, QByteArray erasuresParam);
    QByteArray getDataSymbols(void);
    QByteArray getErrorSymbols(void);

private:
    QByteArray dataSymbols;
    QByteArray errorSymbols;
};

#endif // F2FRAME_H
