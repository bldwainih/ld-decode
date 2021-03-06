/************************************************************************

    efmprocess.cpp

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

#include "efmprocess.h"

EfmProcess::EfmProcess()
{

}

// Note:
//
//   Audio is: EFM->F3->F2->Audio
//    Data is: EFM->F3->F2->F1->Sector->Data
// Section is: EFM->F3->Section
//
// See ECMA-130 for details

bool EfmProcess::process(QString inputEfmFilename, QString outputAudioFilename, QString outputDataFilename, bool verboseDebug)
{
    // Open the input file
    if (!openInputFile(inputEfmFilename)) {
        qCritical("Could not open input file!");
        return false;
    }

    bool processAudio = false;
    bool processData = false;
    if (!outputAudioFilename.isEmpty()) processAudio = true;
    if (!outputDataFilename.isEmpty()) processData = true;

    qint64 inputFileSize = inputFileHandle->size();
    qint64 inputBytesProcessed = 0;
    qint32 lastPercent = 0;

    // Open the audio output file
    if (processAudio) f2FramesToAudio.openOutputFile(outputAudioFilename);

    // Open the data decode output file
    if (processData) sectorsToData.openOutputFile(outputDataFilename);

    // Open the metadata JSON file
    if (processAudio) sectionToMeta.openOutputFile(outputAudioFilename + ".subcode.json");
    if (processData) sectorsToMeta.openOutputFile(outputDataFilename + ".data.json");

    // Turn on verbose debug if required
    if (verboseDebug) efmToF3Frames.setVerboseDebug(true);

    QByteArray efmBuffer;
    while ((efmBuffer = readEfmData()).size() != 0) {
        inputBytesProcessed += efmBuffer.size();

        // Convert the EFM buffer data into F3 frames
        QVector<F3Frame> f3Frames = efmToF3Frames.convert(efmBuffer);

        // Convert the F3 frames into F2 frames
        QVector<F2Frame> f2Frames = f3ToF2Frames.convert(f3Frames);

        // Convert the F2 frames into F1 frames
        QVector<F1Frame> f1Frames = f2ToF1Frames.convert(f2Frames);

        if (processData) {
            // Convert the F1 frames to data sectors
            QVector<Sector> sectors = f1ToSectors.convert(f1Frames);

            // Write the sectors as data
            sectorsToData.convert(sectors);

            // Process the sector meta data
            sectorsToMeta.process(sectors);
        }

        // Convert the F2 frames into audio
        if (processAudio) f2FramesToAudio.convert(f2Frames);

        // Convert the F3 frames into subcode sections
        QVector<Section> sections = f3ToSections.convert(f3Frames);

        // Process the sections to audio metadata
        if (processAudio) sectionToMeta.process(sections);

        // Show EFM processing progress update to user
        qreal percent = (100.0 / static_cast<qreal>(inputFileSize)) * static_cast<qreal>(inputBytesProcessed);
        if (static_cast<qint32>(percent) > lastPercent) qInfo().nospace() << "Processed " << static_cast<qint32>(percent) << "% of the input EFM";
        lastPercent = static_cast<qint32>(percent);
    }

    // Report on the status of the various processes
    reportStatus(processAudio, processData);

    // Close the input file
    closeInputFile();

    // Close the output files
    if (processAudio) f2FramesToAudio.closeOutputFile();
    if (processAudio) sectionToMeta.closeOutputFile();
    if (processData) sectorsToData.closeOutputFile();
    if (processData) sectorsToMeta.closeOutputFile();

    return true;
}

// Method to open the input file for reading
bool EfmProcess::openInputFile(QString inputFileName)
{
    // Open input file for reading
    inputFileHandle = new QFile(inputFileName);
    if (!inputFileHandle->open(QIODevice::ReadOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << inputFileName << "as input file";
        return false;
    }
    qDebug() << "EfmProcess::openInputFile(): 10-bit input file is" << inputFileName << "and is" <<
                inputFileHandle->size() << "bytes in length";

    // Exit with success
    return true;
}

// Method to close the input file
void EfmProcess::closeInputFile(void)
{
    // Is an input file open?
    if (inputFileHandle != nullptr) {
        inputFileHandle->close();
    }

    // Clear the file handle pointer
    delete inputFileHandle;
    inputFileHandle = nullptr;
}

// Method to read EFM T value data from the input file
QByteArray EfmProcess::readEfmData(void)
{
    // Read EFM data in 64K blocks
    qint32 bufferSize = 1240 * 64;

    QByteArray outputData;
    outputData.resize(bufferSize);

    qint64 bytesRead = inputFileHandle->read(outputData.data(), outputData.size());
    if (bytesRead != bufferSize) outputData.resize(static_cast<qint32>(bytesRead));

    return outputData;
}

// Method to write status information to qInfo
void EfmProcess::reportStatus(bool processAudio, bool processData)
{
    efmToF3Frames.reportStatus();
    qInfo() << "";
    f3ToF2Frames.reportStatus();
    qInfo() << "";
    f2ToF1Frames.reportStatus();
    qInfo() << "";

    if (processData) {
        f1ToSectors.reportStatus();
        qInfo() << "";
        sectorsToData.reportStatus();
        qInfo() << "";
        sectorsToMeta.reportStatus();
        qInfo() << "";
    }

    if (processAudio) {
        f2FramesToAudio.reportStatus();
        qInfo() << "";
    }

    f3ToSections.reportStatus();
    qInfo() << "";

    sectionToMeta.reportStatus();
}
