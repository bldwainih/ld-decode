/************************************************************************

    main.cpp

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

#include <QCoreApplication>
#include <QDebug>
#include <QtGlobal>
#include <QCommandLineParser>

#include "ldsprocess.h"

// Global for debug output
static bool showDebug = false;

// Qt debug message handler
void debugOutputHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Use:
    // context.file - to show the filename
    // context.line - to show the line number
    // context.function - to show the function name

    QByteArray localMsg = msg.toLocal8Bit();
    switch (type) {
    case QtDebugMsg: // These are debug messages meant for developers
        if (showDebug) {
            // If the code was compiled as 'release' the context.file will be NULL
            if (context.file != nullptr) fprintf(stderr, "Debug: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
            else fprintf(stderr, "Debug: %s\n", localMsg.constData());
        }
        break;
    case QtInfoMsg: // These are information messages meant for end-users
        if (context.file != nullptr) fprintf(stderr, "Info: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Info: %s\n", localMsg.constData());
        break;
    case QtWarningMsg:
        if (context.file != nullptr) fprintf(stderr, "Warning: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Warning: %s\n", localMsg.constData());
        break;
    case QtCriticalMsg:
        if (context.file != nullptr) fprintf(stderr, "Critical: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Critical: %s\n", localMsg.constData());
        break;
    case QtFatalMsg:
        if (context.file != nullptr) fprintf(stderr, "Fatal: [%s:%d] %s\n", context.file, context.line, localMsg.constData());
        else fprintf(stderr, "Fatal: %s\n", localMsg.constData());
        abort();
    }
}

int main(int argc, char *argv[])
{
    // Install the local debug message handler
    qInstallMessageHandler(debugOutputHandler);

    QCoreApplication a(argc, argv);

    // Set application name and version
    QCoreApplication::setApplicationName("ld-ldstoefm");
    QCoreApplication::setApplicationVersion("1.0");
    QCoreApplication::setOrganizationDomain("domesday86.com");

    // Set up the command line parser
    QCommandLineParser parser;
    parser.setApplicationDescription(
                "ld-ldstoefm - LDS sample to EFM data processing\n"
                "\n"
                "(c)2019 Simon Inns\n"
                "GPLv3 Open-Source - github: https://github.com/happycube/ld-decode");
    parser.addHelpOption();
    parser.addVersionOption();

    // Option to show debug (-d)
    QCommandLineOption showDebugOption(QStringList() << "d" << "debug",
                                       QCoreApplication::translate("main", "Show debug"));
    parser.addOption(showDebugOption);

    // Option to output filtered sample instead of EFM (for testing filters) (-s)
    QCommandLineOption outputSampleOption(QStringList() << "s" << "sample",
                                       QCoreApplication::translate("main", "Output sample instead of EFM (for testing only)"));
    parser.addOption(outputSampleOption);

    // Option to use floating-point filters instead of fixed-point (-f)
    QCommandLineOption useFloatOption(QStringList() << "f" << "float",
                                       QCoreApplication::translate("main", "Use floating-point filters instead of fixed-point"));
    parser.addOption(useFloatOption);

    // Do not apply EFM prefilter (-e)
    QCommandLineOption noEFMOption(QStringList() << "e" << "noefmpre",
                                       QCoreApplication::translate("main", "Do not apply EFM RF filter (for testing only)"));
    parser.addOption(noEFMOption);
    
    // Do not apply ISI filter (-n)
    QCommandLineOption noIsiOption(QStringList() << "n" << "noisi",
                                       QCoreApplication::translate("main", "Do not apply ISI filter"));
    parser.addOption(noIsiOption);

    // Option to limit the percentage of the input file to process
    QCommandLineOption processPercentOption(QStringList() << "p" << "percent",
                                        QCoreApplication::translate("main", "Specify the percent of the input file to process"),
                                        QCoreApplication::translate("main", "percentage (1-100)"));
    parser.addOption(processPercentOption);

    // Positional argument to specify input EFM file
    parser.addPositionalArgument("input", QCoreApplication::translate("main", "Specify input 40MSPS sampled LDS file"));

    // Positional argument to specify output data file
    parser.addPositionalArgument("output", QCoreApplication::translate("main", "Specify output EFM data file"));

    // Process the command line options and arguments given by the user
    parser.process(a);

    // Get the options from the parser
    bool isDebugOn = parser.isSet(showDebugOption);
    bool outputSample = parser.isSet(outputSampleOption);
    bool useFloatingPoint = parser.isSet(useFloatOption);
    bool noIsiFilter = parser.isSet(noIsiOption);
    bool noEFMFilter = parser.isSet(noEFMOption);

    // Get the arguments from the parser
    QString inputFilename;
    QString outputFilename;
    QStringList positionalArguments = parser.positionalArguments();
    if (positionalArguments.count() == 2) {
        inputFilename = positionalArguments.at(0);
        outputFilename = positionalArguments.at(1);
    } else {
        // Quit with error
        qCritical("You must specify an input LDS file and an output EFM file");
        return -1;
    }

    if (inputFilename == outputFilename) {
        // Quit with error
        qCritical("Input and output file names cannot be the same!");
        return -1;
    }

    qint32 percentToProcess = 100;
    if (parser.isSet(processPercentOption)) {
        percentToProcess = parser.value(processPercentOption).toInt();
        if (percentToProcess < 1) percentToProcess = 1;
        if (percentToProcess > 100) percentToProcess = 100;
    }

    // Process the command line options
    if (isDebugOn) showDebug = true;

    // Perform the processing
    LdsProcess ldsProcess;
    ldsProcess.process(inputFilename, outputFilename, outputSample,
                       useFloatingPoint, noEFMFilter, noIsiFilter, percentToProcess);

    // Quit with success
    return 0;
}
