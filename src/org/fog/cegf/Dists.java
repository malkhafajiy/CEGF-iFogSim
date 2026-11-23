package org.fog.cegf;

import java.util.Random;
import org.fog.utils.distribution.Distribution;

/** Seeded distributions (iFogSim's built-ins are not seedable per entity). Times in ms. */
public class Dists {
    /** Periodic with a random first phase. */
    public static class Periodic extends Distribution {
        private final double period; private boolean first = true; private final Random rnd;
        public Periodic(double period, long seed) { this.period = period; this.rnd = new Random(seed); }
        public double getNextValue() { if (first) { first = false; return rnd.nextDouble() * period; } return period; }
        public int getDistributionType() { return Distribution.DETERMINISTIC; }
        public double getMeanInterTransmitTime() { return period; }
    }
    /** Exponential inter-arrival (Poisson process). */
    public static class Poisson extends Distribution {
        private final double mean; private final Random rnd;
        public Poisson(double mean, long seed) { this.mean = mean; this.rnd = new Random(seed); }
        public double getNextValue() { return -mean * Math.log(1 - rnd.nextDouble()); }
        public int getDistributionType() { return Distribution.NORMAL; }
        public double getMeanInterTransmitTime() { return mean; }
    }
}
