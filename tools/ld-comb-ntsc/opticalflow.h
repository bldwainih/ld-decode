/************************************************************************

    opticalflow.h

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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

#ifndef OPTICALFLOW_H
#define OPTICALFLOW_H

#include <QCoreApplication>
#include <QDebug>
#include <QtMath>

// OpenCV3
#include <opencv2/core/core.hpp>
#include <opencv2/video/tracking.hpp>

#include "yiqbuffer.h"

class OpticalFlow
{
public:
    OpticalFlow();

    // Input frame buffer definitions
    struct yiqLine_t {
        YIQ pixel[911]; // One line of YIQ data
    };

    void denseOpticalFlow(YiqBuffer yiqBuffer, QVector<qreal> &kValues);

private:
    // Globals used by the opticalFlow3D method
    cv::Mat previousFrameGrey;
    qint32 framesProcessed;

    cv::Mat convertYtoMat(YiqBuffer yiqBuffer);
    qreal clamp(qreal v, qreal low, qreal high);
    qreal calculateDistance(qreal yDifference, qreal xDifference);
};

#endif // OPTICALFLOW_H
