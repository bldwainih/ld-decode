/************************************************************************

    efmfilter.h

    ld-ldstoefm - LDS sample to EFM data processing
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

#ifndef EFMFILTER_H
#define EFMFILTER_H

#include <QCoreApplication>
#include <QDebug>

class EfmFilter
{
public:
    EfmFilter();
    void floatEfmProcess(QByteArray &inputData);
    void fixedEfmProcess(QByteArray &inputData);

private:
    static const qint32 ceNZeros = 70; // 71 tap filter
    static constexpr qreal ceGain = 8;
    qreal ceXv[ceNZeros+1];

    const qreal ceXcoeffs[ceNZeros+1] = {
        0.002811997668622127, 0.004557434177095733, 0.005518081763120638, 0.006175434988371297,
        0.007079542302379131, 0.007762746564588261, 0.007195457153986951, 0.004856513521712550,
        830.5207151564147810E-6, -0.004778562707971237, -0.011982337787676704, -0.020620652183251653,
       -0.030313333572191556, -0.040603187005666612, -0.050923073987327538, -0.060516949563439962,
       -0.068546464145567254, -0.074232214244951744, -0.076886606768788085, -0.075966051373979687,
       -0.071190271468117655, -0.062596043962852732, -0.050510748183213161, -0.035543389044287388,
       -0.018571164687106789, -653.7572477720859750E-6, 0.017076103040008714, 0.033491741568629191,
        0.047560393829158804, 0.058451726209266315, 0.065610957042443047, 0.068787227432726056,
        0.068052927749701272, 0.063800948413328271, 0.056691533146975850, 0.047573385532196255,
        0.037405276759632830, 0.027164400458192961, 0.017743654186943611, 0.009870181642090168,
        0.004052704260208225, 544.6177383273721940E-6, -667.1955887800581880E-6, 165.1444186576358670E-6,
        0.002601820774369020, 0.006075778653150664, 0.009965935705131752, 0.013676514558850801,
        0.016702483466449127, 0.018675612904669636, 0.019395327506222131, 0.018837755091170524,
        0.017137913326564228, 0.014554762572554125, 0.011427836596406824, 0.008126164613403961,
        0.004996232601002520, 0.002320620946358973, 290.5097959689243230E-6, -0.001009070788039298,
        -0.001598148724027520, -0.001584492210927387, -0.001136622115179061, -452.5692444180374420E-6,
        273.0780338995041350E-6, 878.5749907962782570E-6, 0.001255201534195653, 0.001356950513019374,
        0.001200086984625413, 852.4978004878322510E-6, 415.1503402529320400E-6
    };

    qreal floatEfmFilter(qreal inputSample);

    // Fixed point version (coeff scaled by 15 bits (32768))
    static const qint32 fpTaps = 71;
    qint16 fpXv[fpTaps];
    qint16 offset;

    qint16 fpCoeff[fpTaps] = {
        13, 27, 39, 44, 41, 28, 8, -14, -37, -51, -52, -33, 9, 76, 163, 266, 374, 476, 561, 617, 635,
        611, 547, 448, 326, 199, 85, 5, -21, 17, 132, 323, 581, 890, 1225, 1558, 1857, 2090, 2229, 2254,
        2149, 1915, 1558, 1097, 559, -21, -608, -1164, -1655, -2051, -2332, -2489, -2519, -2432, -2246,
        -1983, -1668, -1330, -993, -675, -392, -156, 27, 159, 235, 254, 231, 202, 180, 149, 92
    };

    qint16 fixedEfmFilter(qint16 inputSample);
};

#endif // EFMFILTER_H
