/************************************************************************

    sector.cpp

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

#include "sector.h"

Sector::Sector()
{
    valid = false;
    qCorrected = false;
    pCorrected = false;
}

// Method to set the sector's data from a F1 frame
void Sector::setData(F1Frame f1Frame)
{
    // Get the f1 data symbols and represent as unsigned 8-bit
    QByteArray f1Data = f1Frame.getDataSymbols();
    uchar* uF1Data = reinterpret_cast<uchar*>(f1Data.data());

    // Get the F1 error symbols
    QByteArray f1Erasures = f1Frame.getErrorSymbols();
    uchar* uF1Erasures = reinterpret_cast<uchar*>(f1Erasures.data());

    // Set the sector's address
    address.setTime(
        bcdToInteger(uF1Data[12]),
        bcdToInteger(uF1Data[13]),
        bcdToInteger(uF1Data[14])
        );

    // Set the sector's mode
    mode = uF1Data[15];

    // Range check the mode and default to 1 if out of range
    if (mode < 0 || mode > 2) {
        qDebug() << "Sector::setData(): Invalid mode of" << mode << "defaulting to 1";
        mode = 1;
    }

    // Process the sector depending on the mode
    if (mode == 0) {
        // Mode 0 sector
        // This is an empty sector filled with 2336 zeros
        userData.fill(0, 2336);
        valid = true;
    } else if (mode == 1) {
        // Mode 1 sector
        // This is a data sector with error correction

        // Perform CRC - since ECC is expensive on processing, we only
        // error correct sector data if the CRC fails

        // Get the 32-bit EDC word from the F1 data
        edcWord =
            ((static_cast<quint32>(uF1Data[2064])) <<  0) |
            ((static_cast<quint32>(uF1Data[2065])) <<  8) |
            ((static_cast<quint32>(uF1Data[2066])) << 16) |
            ((static_cast<quint32>(uF1Data[2067])) << 24);

        // Perform a CRC32 on bytes 0 to 2063 of the F1 frame
        if (edcWord != crc32(uF1Data, 2064)) {
            //qDebug() << "Sector::setData(): Initial EDC failed (CRC32 checksum incorrect)";

            // Attempt Q and P error correction on sector
            performQParityECC(uF1Data, uF1Erasures);
            performPParityECC(uF1Data, uF1Erasures);

            // Get the updated EDC word
            edcWord =
                ((static_cast<quint32>(uF1Data[2064])) <<  0) |
                ((static_cast<quint32>(uF1Data[2065])) <<  8) |
                ((static_cast<quint32>(uF1Data[2066])) << 16) |
                ((static_cast<quint32>(uF1Data[2067])) << 24);

            // Perform EDC again to confirm correction
            if (edcWord != crc32(uF1Data, 2064)) {
                qDebug() << "Sector::setData(): ECC error correction failed - Sector is corrupt!";
                valid = false;
            } else {
                // EDC and ECC are now correct
                qDebug() << "Sector::setData(): ECC error correction successful";
                userData = f1Data.mid(16, 2048);
                valid = true;

                // Set the sector's address again (as the data has been updated)
                address.setTime(
                    bcdToInteger(uF1Data[12]),
                    bcdToInteger(uF1Data[13]),
                    bcdToInteger(uF1Data[14])
                    );
            }
        } else {
            // EDC passed, data is valid.  Copy to sector user data (2048 bytes)
            userData = f1Data.mid(16, 2048);
            valid = true;
        }
    } else if (mode == 2) {
        // Mode 2 sector
        // This is a 2336 byte data sector without error correction
        userData = f1Data.mid(16, 2336);
        valid = true;
    }
}

// Method to get the sector's mode
qint32 Sector::getMode(void)
{
    return mode;
}

// Method to get the sector's address
TrackTime Sector::getAddress(void)
{
    return address;
}

// Method to get the sector's user data
QByteArray Sector::getUserData(void)
{
    return userData;
}

// Method to get the sector's validity
bool Sector::isValid(void)
{
    return valid;
}

// Method to get the corrected flag (i.e. sector was invalid, but corrected by ECC)
bool Sector::isCorrected(void)
{
    if (qCorrected && pCorrected) return true;
    return false;
}

// Private methods ----------------------------------------------------------------------------------------------------

void Sector::performQParityECC(uchar *uF1Data, uchar *uF1Erasures)
{
    // Initialise the RS error corrector
    QRS<255,255-2> qrs; // Up to 251 symbols data load with 2 symbols parity RS(45,43)

    // Keep track of the number of successful corrections
    qint32 successfulCorrections = 0;

    // F1 Data is LSB then MSB
    //
    // RS code is Q(45,43)
    // There are 104 bytes of Q-Parity (52 code words)
    // Each Q field covers 12 to 2248 = 2236 bytes (2 * 1118)
    // 2236 / 43 = 52 Q-parity words (= 104 Q-parity bytes)
    //
    // Calculations are based on ECMA-130 Annex A

    // Ignore the 12 sync bytes
    uF1Data += 12;
    uF1Erasures += 12;

    // Store the data and erasures in the form expected by the ezpwd library
    std::vector<uchar> qField;
    std::vector<int> qFieldErasures;
    qField.resize(45); // 43 + 2 parity bytes = 45

    // evenOdd = 0 = LSBs / evenOdd = 1 = MSBs
    for (qint32 evenOdd = 0; evenOdd < 2; evenOdd++) {
        for (qint32 Nq = 0; Nq < 26; Nq++) {
            qFieldErasures.clear();
            for (qint32 Mq = 0; Mq < 43; Mq++) {
                // Get 43 byte codeword location
                qint32 Vq = 2 * ((44 * Mq + 43 * Nq) % 1118) + evenOdd;
                qField[static_cast<size_t>(Mq)] = uF1Data[Vq];

                // Get codeword erasures if present
                if (uF1Erasures[Vq] == 1) qFieldErasures.push_back(Mq);
            }
            // Get 2 byte parity location
            qint32 qParityByte0 = 2 * ((43 * 26 + Nq) % 1118) + evenOdd;
            qint32 qParityByte1 = 2 * ((44 * 26 + Nq) % 1118) + evenOdd;

            // Note: Q-Parity data starts at 12 + 2236
            qField[43] = uF1Data[qParityByte0 + 2236];
            qField[44] = uF1Data[qParityByte1 + 2236];

            // Perform RS decode/correction
            if (qFieldErasures.size() > 2) qFieldErasures.clear();
            std::vector<int> position;
            int fixed = -1;
            fixed = qrs.decode(qField, qFieldErasures, &position);

            // If correction was successful add to success counter
            // and copy back the corrected data
            if (fixed >= 0) {
                successfulCorrections++;

                // Here we use the calculation in reverse to put the corrected
                // data back into it's original position
                for (qint32 Mq = 0; Mq < 43; Mq++) {
                    qint32 Vq = 2 * ((44 * Mq + 43 * Nq) % 1118) + evenOdd;
                    uF1Data[Vq] = qField[static_cast<size_t>(Mq)];
                }
            }
        }
    }

    // Show Q-Parity correction result to debug
    if (successfulCorrections >= 52) {
        qCorrected = true;
        //qDebug() << "Sector::performQParityECC(): Q-Parity correction successful";

    } else {
        qCorrected = false;
        //qDebug() << "Sector::performQParityECC(): Q-Parity correction failed! Got" << successfulCorrections << "correct out of 52 possible codewords";
    }

    // Reset the pointers
    uF1Data -= 12;
    uF1Erasures -= 12;
}

void Sector::performPParityECC(uchar *uF1Data, uchar *uF1Erasures)
{
    // Initialise the RS error corrector
    QRS<255,255-2> prs; // Up to 251 symbols data load with 2 symbols parity RS(26,24)

    // Keep track of the number of successful corrections
    qint32 successfulCorrections = 0;

    // F1 Data is LSB then MSB
    //
    // RS code is P(26,24)
    // There are 172 bytes of P-Parity (86 code words)
    // Each P field covers 12 to 2076 = 2064 bytes (2 * 1032)
    // 2064 / 24 = 86 P-parity words (= 172 P-parity bytes)
    //
    // Calculations are based on ECMA-130 Annex A

    // Ignore the 12 sync bytes
    uF1Data += 12;
    uF1Erasures += 12;

    // Store the data and erasures in the form expected by the ezpwd library
    std::vector<uchar> pField;
    std::vector<int> pFieldErasures;
    pField.resize(26); // 24 + 2 parity bytes = 26

    // evenOdd = 0 = LSBs / evenOdd = 1 = MSBs
    for (qint32 evenOdd = 0; evenOdd < 2; evenOdd++) {
        for (qint32 Np = 0; Np < 43; Np++) {
            pFieldErasures.clear();
            for (qint32 Mp = 0; Mp < 26; Mp++) {
                // Get 24 byte codeword location + 2 P-parity bytes
                qint32 Vp = 2 * (43 * Mp + Np) + evenOdd;
                pField[static_cast<size_t>(Mp)] = uF1Data[Vp];

                // Get codeword erasures if present
                if (uF1Erasures[Vp] == 1) pFieldErasures.push_back(Mp);
            }

            // Perform RS decode/correction
            if (pFieldErasures.size() > 2) pFieldErasures.clear();
            std::vector<int> position;
            int fixed = -1;
            fixed = prs.decode(pField, pFieldErasures, &position);

            // If correction was successful add to success counter
            // and copy back the corrected data
            if (fixed >= 0) {
                successfulCorrections++;

                // Here we use the calculation in reverse to put the corrected
                // data back into it's original position
                for (qint32 Mp = 0; Mp < 24; Mp++) {
                    qint32 Vp = 2 * (43 * Mp + Np) + evenOdd;
                    uF1Data[Vp] = pField[static_cast<size_t>(Mp)];
                }
            }
        }
    }

    // Show P-Parity correction result to debug
    if (successfulCorrections >= 86) {
        pCorrected = true;
        //qDebug() << "Sector::performPParityECC(): P-Parity correction successful";
    } else {
        pCorrected = false;
        //qDebug() << "Sector::performPParityECC(): P-Parity correction failed! Got" << successfulCorrections << "correct out of 86 possible codewords";
    }

    // Reset the pointers
    uF1Data -= 12;
    uF1Erasures -= 12;
}

// Method to convert 2 digit BCD byte to an integer
qint32 Sector::bcdToInteger(uchar bcd)
{
   return (((bcd>>4)*10) + (bcd & 0xF));
}

// This method is for debug and outputs an array of 8-bit unsigned data as a hex string
QString Sector::dataToString(QByteArray data)
{
    QString output;

    for (qint32 count = 0; count < data.length(); count++) {
        output += QString("%1").arg(static_cast<uchar>(data[count]), 2, 16, QChar('0'));
    }

    return output;
}

// CRC code adapted and used under GPLv3 from:
// https://github.com/claunia/edccchk/blob/master/edccchk.c
quint32 Sector::crc32(uchar *src, qint32 size)
{
    quint32 crc = 0;

    while(size--) {
        crc = (crc >> 8) ^ crc32LUT[(crc ^ (*src++)) & 0xFF];
    }

    return crc;
}
