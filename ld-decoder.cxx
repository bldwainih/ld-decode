/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

const double CHZ = (1000000.0*(315.0/88.0)*8.0);

// b = fir2(32, [0 (3.2/freq) (7.5/freq) (10/freq) (12.5/freq) 1], [0 -.00 1.4 2 0.1 0]); freqz(b)
const double f_boost32_b[] {-7.505745521587810e-04, 5.880141228167600e-04, 3.633494160512888e-04, -4.753259366138748e-04, 1.053434572099664e-03, 1.340894904905588e-03, -4.702405740632102e-03, -2.706299231274282e-03, 8.994775695048057e-03, -2.926960441646054e-02, 3.944247868805379e-02, 5.763183590423128e-04, -3.491893007597012e-02, 2.161049229761215e-01, -3.515066791863503e-01, -1.927783083546432e-01, 6.967256565174642e-01, -1.927783083546432e-01, -3.515066791863503e-01, 2.161049229761215e-01, -3.491893007597013e-02, 5.763183590423131e-04, 3.944247868805381e-02, -2.926960441646055e-02, 8.994775695048059e-03, -2.706299231274281e-03, -4.702405740632101e-03, 1.340894904905589e-03, 1.053434572099664e-03, -4.753259366138747e-04, 3.633494160512898e-04, 5.880141228167604e-04, -7.505745521587810e-04};

const double f_boost36_b[] {-3.800872974256599e-04, 5.463227632743814e-04, -1.010849360995329e-03, 9.374223441419464e-04, 5.927158211435781e-04, -7.372245202944444e-04, 1.520809286284304e-03, 1.803984670597739e-03, -5.944736118414845e-03, -3.245694953221390e-03, 1.032530559813182e-02, -3.241099753141349e-02, 4.241515419548648e-02, 6.053819389472017e-04, -3.601303874450924e-02, 2.198287392936940e-01, -3.541563244423742e-01, -1.931381942172565e-01, 6.967256565174642e-01, -1.931381942172565e-01, -3.541563244423742e-01, 2.198287392936940e-01, -3.601303874450925e-02, 6.053819389472020e-04, 4.241515419548649e-02, -3.241099753141349e-02, 1.032530559813182e-02, -3.245694953221390e-03, -5.944736118414847e-03, 1.803984670597739e-03, 1.520809286284305e-03, -7.372245202944444e-04, 5.927158211435796e-04, 9.374223441419460e-04, -1.010849360995329e-03, 5.463227632743817e-04, -3.800872974256601e-04};

const double f_boost40_b[] {2.909494391224582e-04, -1.938911155585142e-04, -4.870533770014996e-04, 8.173133125248911e-04, -1.574819709681311e-03, 1.421280247212270e-03, 8.517625890831802e-04, -9.992828778089707e-04, 1.951797722088986e-03, 2.206432772568565e-03, -6.976755365473182e-03, -3.678212980439620e-03, 1.136253075646633e-02, -3.480494930772689e-02, 4.463953796893384e-02, 6.268151149007190e-04, -3.681077383098588e-02, 2.225207657182700e-01, -3.560604617812106e-01, -1.933959169783269e-01, 6.967256565174642e-01, -1.933959169783269e-01, -3.560604617812106e-01, 2.225207657182700e-01, -3.681077383098588e-02, 6.268151149007190e-04, 4.463953796893384e-02, -3.480494930772689e-02, 1.136253075646633e-02, -3.678212980439621e-03, -6.976755365473184e-03, 2.206432772568565e-03, 1.951797722088987e-03, -9.992828778089709e-04, 8.517625890831801e-04, 1.421280247212270e-03, -1.574819709681312e-03, 8.173133125248914e-04, -4.870533770014996e-04, -1.938911155585144e-04, 2.909494391224583e-04};

const double f_boost16_b[] {1.332559362229342e-03, -5.345773532279951e-03, 1.182836806945454e-02, 2.636626542153173e-04, -2.179232081607182e-02, 1.677426303390736e-01, -3.151841796082856e-01, -1.876870184544854e-01, 6.967256565174642e-01, -1.876870184544854e-01, -3.151841796082856e-01, 1.677426303390737e-01, -2.179232081607183e-02, 2.636626542153174e-04, 1.182836806945454e-02, -5.345773532279956e-03, 1.332559362229342e-03};

const double f_boost24_b[] {3.924669125894978e-04, 4.510265100480637e-04, -1.829826113723156e-03, -1.290649880814969e-03, 5.163667528638698e-03, -1.956491854690395e-02, 2.974569255267883e-02, 4.774315065423310e-04, -3.107423523773203e-02, 2.027032811687872e-01, -3.418126260665363e-01, -1.914488505853340e-01, 6.967256565174642e-01, -1.914488505853340e-01, -3.418126260665364e-01, 2.027032811687872e-01, -3.107423523773205e-02, 4.774315065423312e-04, 2.974569255267884e-02, -1.956491854690396e-02, 5.163667528638698e-03, -1.290649880814969e-03, -1.829826113723158e-03, 4.510265100480643e-04, 3.924669125894977e-04  };

//  b = fir2(24, [0 (3.2/freq) (7.5/freq) (10/freq) (12.5/freq) 1], [0 -.00 1 1 1 0]); freqz(b)
const double f_bpf24_b[] {-1.921180432047797e-04, 9.929503100862939e-04, -2.582094069894220e-03, 2.570622155800077e-03, -7.660741130044584e-03, 1.416408066195636e-02, -2.287936366852465e-02, 3.473377105004903e-02, -8.499731913489177e-03, 7.245753733005414e-02, -1.478701356333612e-01, -2.166878093553937e-01, 5.628574837085812e-01, -2.166878093553937e-01, -1.478701356333612e-01, 7.245753733005415e-02, -8.499731913489180e-03, 3.473377105004903e-02, -2.287936366852465e-02, 1.416408066195637e-02, -7.660741130044584e-03, 2.570622155800077e-03, -2.582094069894222e-03, 9.929503100862950e-04, -1.921180432047797e-04};

const double f_bpf17_b[] {-5.175062372667873e-04, 6.445489727464134e-05, 1.735906568479843e-03, -7.843589599162782e-03, 3.099947992440967e-02, -1.262098191935197e-02, 7.088358486729855e-02, -3.642426325976681e-01, 2.808858943188426e-01, 2.808858943188426e-01, -3.642426325976680e-01, 7.088358486729859e-02, -1.262098191935197e-02, 3.099947992440965e-02, -7.843589599162787e-03, 1.735906568479845e-03, 6.445489727463979e-05, -5.175062372667875e-04};

const double f_bpf20_b[] {-1.458518564399139e-03, 1.227232735758710e-03, -4.147974577148389e-03, 9.072249765931701e-03, -1.685667550321525e-02, 2.845921244440753e-02, -7.529965679711438e-03, 6.786123057094691e-02, -1.437377358332911e-01, -2.151820893431397e-01, 5.628574837085812e-01, -2.151820893431398e-01, -1.437377358332911e-01, 6.786123057094694e-02, -7.529965679711440e-03, 2.845921244440753e-02, -1.685667550321525e-02, 9.072249765931704e-03, -4.147974577148391e-03, 1.227232735758710e-03, -1.458518564399139e-03};

const double f_bpf16_b[] {-1.976965452914732e-03, 3.870088563376442e-03, -9.097973906203210e-03, 1.918180543275707e-02, -5.960850952317086e-03, 5.996063719123673e-02, -1.363505143870683e-01, -2.124300498488513e-01, 5.628574837085812e-01, -2.124300498488513e-01, -1.363505143870683e-01, 5.996063719123675e-02, -5.960850952317086e-03, 1.918180543275706e-02, -9.097973906203214e-03, 3.870088563376446e-03, -1.976965452914732e-03};

const double f_bpf32_b[] {1.237993860705637e-05, 1.936187726546904e-04, -2.670982516201244e-05, 4.454325083970799e-04, -5.156709575865214e-04, 2.952026060457620e-03, -6.635632689937511e-03, 5.390209124526889e-03, -1.334451680717444e-02, 2.118981670710334e-02, -3.033779806248773e-02, 4.192791983899118e-02, -9.551370840857498e-03, 7.724803680268165e-02, -1.520638395528439e-01, -2.181925313256816e-01, 5.628574837085812e-01, -2.181925313256816e-01, -1.520638395528438e-01, 7.724803680268164e-02, -9.551370840857498e-03, 4.192791983899118e-02, -3.033779806248774e-02, 2.118981670710335e-02, -1.334451680717444e-02, 5.390209124526888e-03, -6.635632689937510e-03, 2.952026060457623e-03, -5.156709575865216e-04, 4.454325083970799e-04, -2.670982516201222e-05, 1.936187726546907e-04, 1.237993860705637e-05};

// bandpass_filter = sps.firwin2(19, [0, (3.2/freq), (7.5/freq), (10/freq), (12.5/freq), 1], [0, -.00, 1, 1, 1, 0], antisymmetric=True)
//const double f_bpf18_python_b[] {-1.045921072580550e-04 , 7.444554938137628e-04 , 1.247673444329816e-03 , -3.474213074594388e-03 , 2.157334973336405e-02 , -3.159923622452770e-02 , 1.084750324236225e-02 , -2.131896036395598e-01 , 4.166820508198082e-01 , 0.000000000000000e+00 , -4.166820508198078e-01 , 2.131896036395600e-01 , -1.084750324236239e-02 , 3.159923622452771e-02 , -2.157334973336404e-02 , 3.474213074594340e-03 , -1.247673444329798e-03 , -7.444554938137861e-04 , 1.045921072580680e-04};

// bandpass_filter = sps.firwin(19, [3.5/freq, 13.5/freq], pass_zero=False) 
const double f_bpf18_python_b[] {1.161716633889564e-03 , -3.645941636432679e-03 , 1.481452792605961e-02 , 1.870794350474106e-03 , 4.166707106713363e-02 , -3.584158660448544e-02 , -1.878244316164251e-02 , -1.915540895026864e-01 , -1.594807494394026e-01 , 6.973541197640782e-01 , -1.594807494394026e-01 , -1.915540895026864e-01 , -1.878244316164251e-02 , -3.584158660448544e-02 , 4.166707106713365e-02 , 1.870794350474108e-03 , 1.481452792605962e-02 , -3.645941636432679e-03 , 1.161716633889564e-03};

const double f_bpf19_python_b[] {-1.913533040896089e-03 , -7.743409477081318e-04 , 2.084562270948399e-03 , 1.912856241331821e-02 , 8.207888832465593e-03 , 4.089062838706278e-02 , -8.222875630813928e-02 , -4.198859652152448e-03 , -3.763597959365195e-01 , 3.931238816727631e-01 , 3.931238816727632e-01 , -3.763597959365196e-01 , -4.198859652152448e-03 , -8.222875630813926e-02 , 4.089062838706280e-02 , 8.207888832465598e-03 , 1.912856241331822e-02 , 2.084562270948397e-03 , -7.743409477081318e-04 , -1.913533040896089e-03};

const double f_bpf24_python_b[] {4.619731338735579e-04 , -1.082523173778389e-03 , 2.367278776554692e-04 , -2.807394412624918e-04 , 2.141991982608351e-03 , 2.799280159917252e-03 , -6.051855033164363e-03 , 3.090064589652045e-02 , -3.925192625774489e-02 , 1.218962282807741e-02 , -2.241769069815310e-01 , 4.218537373143370e-01 , 0.000000000000000e+00 , -4.218537373143363e-01 , 2.241769069815313e-01 , -1.218962282807779e-02 , 3.925192625774489e-02 , -3.090064589652027e-02 , 6.051855033164387e-03 , -2.799280159917397e-03 , -2.141991982608299e-03 , 2.807394412625436e-04 , -2.367278776555044e-04 , 1.082523173778389e-03 , -4.619731338735434e-04};

// bandpass_filter = sps.firwin(26, [3.5/freq, 13.5/freq], pass_zero=False)
const double f_bpf25_python_b[] {-9.176497499876675e-04 , -2.233684967277756e-04 , -5.349117887401467e-03 , -4.901882445519524e-03 , -2.168940507623545e-03 , 4.691676333653247e-03 , 3.394332534214696e-02 , 1.205004889347425e-02 , 5.212591687899472e-02 , -9.465160938904488e-02 , -4.503394495977535e-03 , -3.860712181301405e-01 , 3.946733981844408e-01 , 3.946733981844408e-01 , -3.860712181301405e-01 , -4.503394495977537e-03 , -9.465160938904486e-02 , 5.212591687899470e-02 , 1.205004889347425e-02 , 3.394332534214698e-02 , 4.691676333653248e-03 , -2.168940507623545e-03 , -4.901882445519527e-03 , -5.349117887401476e-03 , -2.233684967277757e-04 , -9.176497499876675e-04};

//const double f_bpf25_python_b[] {1.659854374172136e-03 , -3.271343550244608e-03 , -9.733111910836683e-04 , -1.119713433918507e-02 , 6.440357095792324e-03 , -6.167933604399260e-03 , 4.646226376364330e-02 , -1.599902752699241e-03 , 6.545542450927930e-02 , -1.065283831613872e-01 , 5.228961320632065e-03 , -3.910298388210229e-01 , 3.955030930887304e-01 , 3.955030930887304e-01 , -3.910298388210229e-01 , 5.228961320632066e-03 , -1.065283831613872e-01 , 6.545542450927928e-02 , -1.599902752699241e-03 , 4.646226376364333e-02 , -6.167933604399262e-03 , 6.440357095792321e-03 , -1.119713433918508e-02 , -9.733111910836700e-04 , -3.271343550244610e-03 , 1.659854374172136e-03};

const double f_lpf42_16_python_b[] {2.806676426568827e-03 , 8.678237335678843e-04 , -7.758994442967244e-03 , -2.292786181447184e-02 , -2.214853573118029e-02 , 2.782699125184042e-02 , 1.319713476036243e-01 , 2.434340451329033e-01 , 2.918570156802296e-01 , 2.434340451329033e-01 , 1.319713476036244e-01 , 2.782699125184043e-02 , -2.214853573118030e-02 , -2.292786181447184e-02 , -7.758994442967246e-03 , 8.678237335678851e-04 , 2.806676426568827e-03};

const double f_lpf45_16_python_b[] { 3.165390390504862e-03 , 3.060141452169122e-03 , -3.984544684717678e-03 , -2.248680062518488e-02 , -3.091815939876376e-02 , 1.350373945897430e-02 , 1.260523263298884e-01 , 2.551817689904604e-01 , 3.128522761733384e-01 , 2.551817689904605e-01 , 1.260523263298884e-01 , 1.350373945897431e-02 , -3.091815939876376e-02 , -2.248680062518488e-02 , -3.984544684717680e-03 , 3.060141452169125e-03 , 3.165390390504862e-03 };

const double f_lpf45_17_python_b[] { 3.165390390504862e-03 , 3.060141452169122e-03 , -3.984544684717678e-03 , -2.248680062518488e-02 , -3.091815939876376e-02 , 1.350373945897430e-02 , 1.260523263298884e-01 , 2.551817689904604e-01 , 3.128522761733384e-01 , 2.551817689904605e-01 , 1.260523263298884e-01 , 1.350373945897431e-02 , -3.091815939876376e-02 , -2.248680062518488e-02 , -3.984544684717680e-03 , 3.060141452169125e-03 , 3.165390390504862e-03 };

const double f_lpf50_16_python_b[] {1.916071020215727e-03 , 5.134814884462994e-03 , 3.347495595196464e-03 , -1.653628437323453e-02 , -4.060917271174611e-02 , -1.128852987551174e-02 , 1.114703592770741e-01 , 2.724978912765220e-01 , 3.481347098140423e-01 , 2.724978912765220e-01 , 1.114703592770741e-01 , -1.128852987551175e-02 , -4.060917271174612e-02 , -1.653628437323453e-02 , 3.347495595196465e-03 , 5.134814884462999e-03 , 1.916071020215727e-03};

//const double f_lpf50_32_python_b[] {-0.00153514027372 , -0.00128484804517 , 0.000896191796755 , 0.00383478453322 , 0.00321506486168 , -0.0039443397662 , -0.0116050394341 , -0.00692331358262 , 0.0129993404531 , 0.0282577143598 , 0.011219288771 , -0.0363293568899 , -0.0654014729708 , -0.0146172118449 , 0.124949497855 , 0.281315083295 , 0.349907513762 , 0.281315083295 , 0.124949497855 , -0.0146172118449 , -0.0654014729708 , -0.0363293568899 , 0.011219288771 , 0.0282577143598 , 0.0129993404531 , -0.00692331358262 , -0.0116050394341 , -0.0039443397662 , 0.00321506486168 , 0.00383478453322 , 0.000896191796755 , -0.00128484804517 , -0.00153514027372 };

//const double f_lpf55_16_python_b[] {-0.000723397637219 , 0.00433368634435 , 0.00931049560886 , -0.00571459940902 , -0.0426674090828 , -0.0349785521301 , 0.0915883051498 , 0.286887403184 , 0.383928135944 , 0.286887403184 , 0.0915883051498 , -0.0349785521301 , -0.0426674090828 , -0.00571459940902 , 0.00931049560886 , 0.00433368634435 , -0.000723397637219};

Filter f_lpf(16, NULL, f_lpf50_16_python_b);

// From http://lists.apple.com/archives/perfoptimization-dev/2005/Jan/msg00051.html. 
const double PI_FLOAT = M_PIl;
const double PIBY2_FLOAT = (M_PIl/2.0); 
// |error| < 0.005
double fast_atan2( double y, double x )
{
	if ( x == 0.0f )
	{
		if ( y > 0.0f ) return PIBY2_FLOAT;
		if ( y == 0.0f ) return 0.0f;
		return -PIBY2_FLOAT;
	}
	double atan;
	double z = y/x;
	if (  fabs( z ) < 1.0f  )
	{
		atan = z/(1.0f + 0.28f*z*z);
		if ( x < 0.0f )
		{
			if ( y < 0.0f ) return atan - PI_FLOAT;
			return atan + PI_FLOAT;
		}
	}
	else
	{
		atan = PIBY2_FLOAT - z/(z*z + 0.28f);
		if ( y < 0.0f ) return atan - PI_FLOAT;
	}
	return atan;
}


typedef vector<complex<double>> v_cossin;

class FM_demod {
	protected:
		double ilf;
		vector<Filter> f_q, f_i;
		vector<Filter *> f_pre;
		Filter *f_post;

		vector<v_cossin> ldft;
		double avglevel[40];

		double cbuf[9];
	
		int linelen;

		int min_offset;

		double deemp;

		vector<double> fb;
	public:
		FM_demod(int _linelen, vector<double> _fb, vector<Filter *> prefilt, vector<Filter *> filt, Filter *postfilt) {
			int i = 0;
			linelen = _linelen;

			fb = _fb;

			ilf = 8600000;
			deemp = 0;

			for (double f : fb) {
				v_cossin tmpdft;
				double fmult = f / CHZ; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
					// cerr << sin(i * 2.0 * M_PIl * fmult) << ' ' << cos(i * 2.0 * M_PIl * fmult) << endl;
				}	
				ldft.push_back(tmpdft);

				f_i.push_back(Filter(filt[i]));
				f_q.push_back(Filter(filt[i]));

				i++;
			}

			f_pre = prefilt;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

			for (int i = 0; i < 40; i++) avglevel[i] = 30;
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

			min_offset = 128;
		}

		~FM_demod() {
//			if (f_pre) free(f_pre);
			if (f_post) free(f_post);
		}

		vector<double> process(vector<double> in) 
		{
			vector<double> out;
			vector<double> phase(fb.size() + 1);
			vector<double> level(fb.size() + 1);
			double avg = 0, total = 0.0;
			
			for (int i = 0; i < 9; i++) cbuf[i] = 8100000;

			if (in.size() < (size_t)linelen) return out;

			for (double n : in) avg += n / in.size();
			//cerr << avg << endl;

			int i = 0;
			for (double n : in) {
				vector<double> angle(fb.size() + 1);
				double peak = 500000, pf = 0.0;
				int npeak;
				int j = 0;

			//	n -= avg;
				total += fabs(n);
				for (Filter *f: f_pre) {
					n = f->feed(n);
				}

				angle[j] = 0;

//				cerr << i << ' ';
	
				for (double f: fb) {
					double fci = f_i[j].feed(n * ldft[j][i].real());
					double fcq = f_q[j].feed(-n * ldft[j][i].imag());
					double at2 = fast_atan2(fci, fcq);	
	
//					cerr << n << ' ' << fci << ' ' << fcq << ' ' ;

					level[j] = ctor(fci, fcq);
	
					angle[j] = at2 - phase[j];
					if (angle[j] > M_PIl) angle[j] -= (2 * M_PIl);
					else if (angle[j] < -M_PIl) angle[j] += (2 * M_PIl);
					
//					cerr << at2 << ' ' << angle[j] << ' '; 
				//	cerr << angle[j] << ' ';
						
					if (fabs(angle[j]) < fabs(peak)) {
						npeak = j;
						peak = angle[j];
						pf = f + ((f / 2.0) * angle[j]);
					}
//					cerr << pf << endl;
					phase[j] = at2;

				//	cerr << f << ' ' << pf << ' ' << f + ((f / 2.0) * angle[j]) << ' ' << fci << ' ' << fcq << ' ' << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}
	
				double thisout = pf;	
//				cerr << pf << endl;

				if (f_post) thisout = f_post->feed(pf);	
				if (i > min_offset) {
					int bin = (thisout - 7600000) / 200000;
					if (1 || bin < 0) bin = 0;

					avglevel[bin] *= 0.9;
					avglevel[bin] += level[npeak] * .1;

//					if (fabs(shift) > 50000) thisout += shift;
//					cerr << ' ' << thisout << endl ;
//					out.push_back(((level[npeak] / avglevel[bin]) * 1200000) + 7600000); 
//					out.push_back((-(level[npeak] - 30) * (1500000.0 / 10.0)) + 9300000); 
					out.push_back(((level[npeak] / avglevel[bin]) > 0.3) ? thisout : 0);
//					out.push_back(thisout);
				};
				i++;
			}

//			cerr << total / in.size() << endl;
			return out;
		}
};

bool triple_hdyne = true;

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1;
	//double output[2048];
	unsigned char inbuf[2048];

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;

	if (argc >= 2 && (strncmp(argv[1], "-", 1))) {
		fd = open(argv[1], O_RDONLY);
	}

	if (argc >= 3) {
		unsigned long long offset = atoll(argv[2]);

		if (offset) lseek64(fd, offset, SEEK_SET);
	}
		
	if (argc >= 4) {
		if ((size_t)atoll(argv[3]) < dlen) {
			dlen = atoll(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	Filter f_boost36(36, NULL, f_boost36_b);
	Filter f_boost40(40, NULL, f_boost40_b);
	Filter f_boost24(24, NULL, f_boost24_b);
	Filter f_bpf20(20, NULL, f_bpf20_b);
	Filter f_bpf18(18, NULL, f_bpf18_python_b);
	Filter f_bpf19(19, NULL, f_bpf19_python_b);
	Filter f_bpf25(25, NULL, f_bpf25_python_b);
	Filter f_bpf17(17, NULL, f_bpf17_b);
	Filter f_boost32(32, NULL, f_boost32_b);

	//FM_demod video(2048, {8100000, 8500000, 8900000, 9300000, 9700000}, {&f_bpf18}, {&f_lpf, &f_lpf, &f_lpf, &f_lpf, &f_lpf}, NULL);
	FM_demod video(2048, {8100000, 8500000, 8900000, 9300000}, {&f_boost32}, {&f_lpf, &f_lpf, &f_lpf, &f_lpf, &f_lpf}, NULL);

	double charge = 0, acharge = 0, prev = 8700000;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);

		vector<unsigned short> bout;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];
			int in;

			if (n > 0) {
//				cerr << i << ' ' << n << ' ';
				charge += ((n - prev) * 1.0);
				acharge += fabs((n - prev) * 1.0);
				prev = n;

				double f = .65;

//				cerr << i << ' ' << charge << ' ' << acharge << endl;

				if (fabs(acharge) < 250000.0) f = 1.0;
				else if (fabs(acharge) < 500000.0) f = 1.0 - ((1.0 - f) * ((acharge - 250000.0) / 250000.0));
//				else if (fabs(acharge) > 2000000.0) f -= (0.5 * (1.0 - ((acharge - 2000000) / 2000000.0)));

				n -= (charge * f);
//				n -= (charge * .5);
//				cerr << n << ' ' << charge << ' ' << acharge << ' ' << endl;
				charge *= 0.88;
				acharge *= 0.88;
//				cerr << charge << ' ' << endl;

				n -= 7600000.0;
				n /= (9300000.0 - 7600000.0);
				if (n < 0) n = 0;
				in = 1 + (n * 57344.0);
				if (in > 65535) in = 65535;
//				cerr << in << endl;
			} else {
				in = 0;
			}

			bout.push_back(in);
		}
		
		unsigned short *boutput = bout.data();
		int len = outline.size();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

		i += (len > 1820) ? 1820 : len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		//cerr << i << ' ' << rv << endl;
	}
	return 0;
}

