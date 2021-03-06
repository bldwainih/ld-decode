/************************************************************************

    efmtof3frames.cpp

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

#include "efmtof3frames.h"

EfmToF3Frames::EfmToF3Frames()
{
    // Initialise the state machine
    currentState = state_initial;
    nextState = currentState;
    waitingForData = false;

    validFrameLength = 0;
    invalidFrameLength = 0;
    syncLoss = 0;

    firstF3AfterInitialSync = false;

    verboseDebug = false;
}

// Method to write status information to qInfo
void EfmToF3Frames::reportStatus(void)
{
    qInfo() << "EFM to F3 Frame converter:";
    qInfo() << "  Total number of F3 Frames =" << validFrameLength + invalidFrameLength;
    qInfo() << "  of which" << validFrameLength << "were 588 bits and" << invalidFrameLength << "were invalid lengths";
    qInfo() << "  Lost frame sync" << syncLoss << "times";
}

// Turn verbose debug on/off
void EfmToF3Frames::setVerboseDebug(bool param)
{
    verboseDebug = param;
}

// Convert the EFM buffer data into F3 frames
// Note: this method is reentrant - any unused EFM buffer data
// is stored by the class and used in addition to the passed EFM
// buffer data to ensure no data is lost between conversion calls
QVector<F3Frame> EfmToF3Frames::convert(QByteArray efmDataIn)
{
    waitingForData = false;

    // Append the incoming EFM data to the buffer
    efmData.append(efmDataIn);

    // Clear any existing F3 frames from the buffer
    f3Frames.clear();

    while (!waitingForData) {
        currentState = nextState;

        switch (currentState) {
        case state_initial:
            nextState = sm_state_initial();
            break;
        case state_findInitialSyncStage1:
            nextState = sm_state_findInitialSyncStage1();
            break;
        case state_findInitialSyncStage2:
            nextState = sm_state_findInitialSyncStage2();
            break;
        case state_findSecondSync:
            nextState = sm_state_findSecondSync();
            break;
        case state_syncLost:
            nextState = sm_state_syncLost();
            break;
        case state_processFrame:
            nextState = sm_state_processFrame();
            break;
        }
    }

    return f3Frames;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_initial(void)
{
    return state_findInitialSyncStage1;
}

// Search for the first T11+T11 sync pattern in the EFM buffer
EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_findInitialSyncStage1(void)
{
    // Find the first T11+T11 sync pattern in the EFM buffer
    qint32 startSyncTransition = -1;

    for (qint32 i = 0; i < efmData.size() - 1; i++) {
        if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
            startSyncTransition = i;
            break;
        }
    }

    if (startSyncTransition == -1) {
        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage1(): No initial F3 sync found in EFM buffer, requesting more data";

        // Discard the EFM already tested and try again
        removeEfmData(efmData.size() - 1);

        waitingForData = true;
        return state_findInitialSyncStage1;
    }

    if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage1(): Initial F3 sync found at buffer position" << startSyncTransition;

    // Discard all EFM data up to the sync start
    removeEfmData(startSyncTransition);

    // Move to find initial sync stage 2
    return state_findInitialSyncStage2;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_findInitialSyncStage2(void)
{
    // Find the next T11+T11 sync pattern in the EFM buffer
    endSyncTransition = -1;
    qint32 tTotal = 11;

    qint32 searchLength = 588 * 4;

    for (qint32 i = 1; i < efmData.size() - 1; i++) {
        if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
            endSyncTransition = i;
            break;
        }
        tTotal += efmData[i];

        // If we are more than a few F3 frame lengths out, give up
        if (tTotal > searchLength) {
            endSyncTransition = i;
            break;
        }
    }

    if (tTotal > searchLength) {
        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): No second F3 sync found within a reasonable length, going back to look for new initial sync.  T =" << tTotal;
        removeEfmData(endSyncTransition);
        return state_findInitialSyncStage1;
    }

    if (endSyncTransition == -1) {
        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): No second F3 sync found in EFM buffer, requesting more data.  T =" << tTotal;

        waitingForData = true;
        return state_findInitialSyncStage2;
    }

    // Is the frame length valid (or close enough)?
    if (tTotal < 587 || tTotal > 589) {
        // Discard the transitions already tested and try again
        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): Got second F3 initial sync at" <<
                                      endSyncTransition << "but frame length was" << tTotal << " - trying again";
        removeEfmData(endSyncTransition);
        return state_findInitialSyncStage2;
    }

    if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findInitialSyncStage2(): Found first F3 frame with a length of" << tTotal << "bits";

    // Mark F3 frame as first after F3 initial sync
    firstF3AfterInitialSync = true;

    return state_processFrame;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_findSecondSync(void)
{
    // Get at least 588 bits of data
    qint32 i = 0;
    qint32 tTotal = 0;
    while (i < efmData.size() && tTotal < 588) {
        tTotal += efmData[i];
        i++;
    }

    // Did we have enough data to reach a tTotal of 588?
    if (tTotal < 588) {
        //if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): Need more data to reach required F3 frame length";
        // Indicate that more deltas are required and stay in this state
        waitingForData = true;
        return state_findSecondSync;
    }

    // Do we have enough data to verify the sync position?
    if ((efmData.size() - i) < 2) {
        //if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): Need more data to verify F3 sync position";
        // Indicate that more deltas are required and stay in this state
        waitingForData = true;
        return state_findSecondSync;
    }

    // Is tTotal correct?
    if (tTotal == 588) {
        endSyncTransition = i;
        poorSyncCount = 0;
    } else {
        // Handle various possible sync issues in a (hopefully) smart way
        if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
            if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync is in the right position and is valid - frame contains invalid T value";
            endSyncTransition = i;
            poorSyncCount = 0;
        } else if (efmData[i - 1] == static_cast<char>(11) && efmData[i] == static_cast<char>(11)) {
            if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync valid, but off by one transition backwards";
            endSyncTransition = i - 1;
            poorSyncCount = 0;
        } else if (efmData[i - 1] >= static_cast<char>(10) && efmData[i] >= static_cast<char>(10)) {
            if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync value low and off by one transition backwards";
            endSyncTransition = i - 1;
            poorSyncCount = 0;
        } else {
            if (abs(tTotal - 588) < 3) {
                if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 frame length was incorrect (" << tTotal
                         << "), but error is less than T3, so nothing much to do about it";
                endSyncTransition = i;
                poorSyncCount = 0;
            } else if (abs(tTotal - 588) >= 3) {
                    if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 frame length was incorrect (" << tTotal
                             << "), moving end transition in attempt to correct";
                    if (tTotal > 588) endSyncTransition = i - 1; else endSyncTransition = i;
                    poorSyncCount = 0;
            } else if (efmData[i] == static_cast<char>(11) && efmData[i + 1] == static_cast<char>(11)) {
                if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync valid, but off by one transition forward";
                endSyncTransition = i;
                poorSyncCount = 0;
            } else if (efmData[i] >= static_cast<char>(10) && efmData[i + 1] >= static_cast<char>(10)) {
                if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync value low and off by one transition forward";
                endSyncTransition = i;
                poorSyncCount = 0;
            } else {
                if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): F3 Sync appears to be missing causing an" <<
                            "overshoot; dropping a T value and marking as poor sync #" << poorSyncCount;
                endSyncTransition = i;
                poorSyncCount++;
            }
        }
    }

    // Hit limit of poor sync detections?
    if (poorSyncCount > 16) {
        poorSyncCount = 0;
        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_findSecondSync(): Too many F3 sequential poor sync detections (>16) - sync lost";
        return state_syncLost;
    }

    // Move to the process frame state
    return state_processFrame;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_syncLost(void)
{
    if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_syncLost(): F3 Sync was completely lost!";
    syncLoss++;
    return state_findInitialSyncStage1;
}

EfmToF3Frames::StateMachine EfmToF3Frames::sm_state_processFrame(void)
{
    QVector<qint32> frameT(endSyncTransition);
    qint32 tTotal = 0;
    for (qint32 delta = 0; delta < endSyncTransition; delta++) {
        qint32 value = efmData[delta];

        if (value < 3) {
            if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_processFrame(): Invalid T value <3";
        }
        if (value > 11) {
            if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_processFrame(): Invalid T value >11";
        }

        tTotal += value;
        frameT[delta] = value;
    }
    if (tTotal == 588) {
        validFrameLength++;
//        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_processFrame(): F3 Frame" <<
//                                      validFrameLength + invalidFrameLength << "length correct";
    } else {
        invalidFrameLength++;
        if (verboseDebug) qDebug() << "EfmToF3Frames::sm_state_processFrame(): F3 Frame" <<
                                      validFrameLength + invalidFrameLength << "frame length incorrect T =" << tTotal;
    }

    // Discard all transitions up to the sync end
    removeEfmData(endSyncTransition);

    // Store the F3 Frame
    F3Frame newFrame;
    newFrame.setTValues(frameT);
    if (firstF3AfterInitialSync) newFrame.setFirstAfterSync(true); else newFrame.setFirstAfterSync(false);
    firstF3AfterInitialSync = false;
    f3Frames.append(newFrame);

    // Find the next sync position
    return state_findSecondSync;
}

// Method to remove EFM data from the start of the buffer
void EfmToF3Frames::removeEfmData(qint32 number)
{
    if (number > efmData.size()) {
        efmData.clear();
    } else {
        // Shift the byte array back by 'number' elements
        efmData.remove(0, number);
    }
}
