/************************************************************************

    snranalysisdialog.h

    ld-analyse - TBC output analysis
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#ifndef SNRANALYSISDIALOG_H
#define SNRANALYSISDIALOG_H

#include <QDialog>
#include <QtCharts>

#include "lddecodemetadata.h"

namespace Ui {
class SnrAnalysisDialog;
}

class SnrAnalysisDialog : public QDialog
{
    Q_OBJECT

public:
    explicit SnrAnalysisDialog(QWidget *parent = nullptr);
    ~SnrAnalysisDialog();

    void updateChart(LdDecodeMetaData *ldDecodeMetaData);

private:
    Ui::SnrAnalysisDialog *ui;

    QChart chart;
    QLineSeries series;
    QChartView *chartView;
    QValueAxis axisX;
    QValueAxis axisY;
};

#endif // SNRANALYSISDIALOG_H